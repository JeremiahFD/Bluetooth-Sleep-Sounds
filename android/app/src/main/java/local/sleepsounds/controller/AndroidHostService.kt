package local.sleepsounds.controller

import android.app.*
import android.content.*
import android.media.*
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.*
import android.util.Base64
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.InputStream
import java.security.SecureRandom
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/** Independent Android playback host. No Pi audio, settings or pairing commands. */
class AndroidHostService : Service() {
    companion object { @Volatile var running = false; const val CHANNEL = "sleep-sounds-playback" }
    private val main = Handler(Looper.getMainLooper())
    private lateinit var prefs: android.content.SharedPreferences
    private lateinit var audio: AudioManager
    private lateinit var focus: AudioFocusRequest
    private lateinit var session: MediaSession
    private var server: HostHttpServer? = null
    private var player: MediaPlayer? = null
    private lateinit var library:HostLibrary
    private var equalizer:android.media.audiofx.Equalizer?=null
    private var gainDb=0.0
    private var eqEnabled=false
    private var eqAvailable=false
    private var bypass=false
    private var eqLevels=JSONArray(listOf(0,0,0,0,0))
    private var revision=0
    private var activeProfile="none"
    private var playMode="loop"
    private var tickAt=0L
    private val statsTask=object:Runnable{override fun run(){account();main.postDelayed(this,30000)}}
    private fun account(){val now=SystemClock.elapsedRealtime();if(ready&&!paused&&tickAt>0)library.played(selected,activeProfile,(now-tickAt)/1000.0);tickAt=now}
    private fun releaseEffects(){equalizer?.release();equalizer=null;eqAvailable=false}
    private fun applyEffects(){
        val level=(volume/100.0 * if(bypass)1.0 else Math.pow(10.0,gainDb/20)).toFloat()
        player?.setVolume(level,level)
        equalizer?.let{eq->
            val range=eq.bandLevelRange
            for(i in 0 until eq.numberOfBands.toInt()) {val f=eq.getCenterFreq(i.toShort())/1000.0;val frequencies=listOf(125.0,500.0,1000.0,4000.0,8000.0);val nearest=frequencies.indices.minBy{ kotlin.math.abs(kotlin.math.ln(f/frequencies[it])) };eq.setBandLevel(i.toShort(),(eqLevels.optDouble(nearest,0.0)*100).toInt().coerceIn(range[0].toInt(),range[1].toInt()).toShort())}
            eq.enabled=eqEnabled&&!bypass
        }
    }
    private fun audioSettings()=JSONObject().put("gain_db",gainDb).put("bypass",bypass).put("gain_enabled",true).put("eq_enabled",eqEnabled).put("eq_levels",eqLevels)
    fun config():JSONObject=JSONObject().put("platform","android").put("volume",volume).put("loop",loop).put("play_mode",playMode)
        .put("formats",JSONArray(listOf(".m4a",".aac",".mp3",".flac",".wav",".ogg",".opus",".mp4",".webm")))
        .put("max_upload_bytes",900000000).put("storage_reserve_mb",128).put("free_storage_bytes",tracksDir.usableSpace)
        .put("sleep_minutes",prefs.getInt("sleep_minutes",60)).put("allow_track_deletion",prefs.getBoolean("allow_track_deletion",false))
        .put("audio_processing",audioSettings()).put("audio_processing_revision",revision).put("normalization",false)
        .put("audio_buffer_seconds",0.5).put("auto_reconnect",false).put("resume_after_restart",false).put("reconnect_retry_minutes",10)
        .put("android_eq_available",eqAvailable).put("audio_rack_supported",false).put("audio_presets_supported",false)
    fun readApi(path:String,uri:android.net.Uri):Any?=library.get(path,uri)?:when(path){
        "/api/config"->config()
        "/api/outputs"->JSONObject().put("selected","android/system").put("devices",JSONArray().put(JSONObject().put("name","android/system").put("description","Android system output (HDMI / Bluetooth)")))
        "/api/alarm"->JSONObject().put("supported",false)
        "/api/app-release"->JSONObject().put("available",false).put("message","Android alpha build "+BuildConfig.VERSION_NAME+". Updates are installed separately during testing.")
        "/api/system"->JSONObject().put("host",name()).put("model",Build.MODEL).put("os","Android "+Build.VERSION.RELEASE).put("app_version",BuildConfig.VERSION_NAME).put("uptime_seconds",SystemClock.elapsedRealtime()/1000).put("storage_free_bytes",tracksDir.usableSpace).put("storage_total_bytes",tracksDir.totalSpace).put("audio_output","Android system output").put("capabilities",JSONObject().put("restart_app",false).put("restart_host",false).put("shutdown",false))
        else->null
    }
    private val artDir get()=File(filesDir,"host-artwork").apply{mkdirs()}
    private fun artFile(key:String):File {audioFile(key);return File(artDir,java.security.MessageDigest.getInstance("SHA-256").digest(key.toByteArray()).joinToString(""){"%02x".format(it)}+".img")}
    fun artworkUrl(key:String):String?=if(artFile(key).isFile)"/api/artwork?track="+android.net.Uri.encode(key)else null
    fun artwork(key:String):ByteArray?=artFile(key).takeIf{it.isFile}?.readBytes()
    fun importArtwork(key:String,input:InputStream,length:Long):JSONObject {
        require(audioFile(key).isFile&&length in 1..8388608);val bytes=ByteArray(length.toInt());var at=0;while(at<bytes.size){val n=input.read(bytes,at,bytes.size-at);require(n>0);at+=n}
        val options=android.graphics.BitmapFactory.Options().apply{inJustDecodeBounds=true};android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.size,options)
        require(options.outWidth in 1..8192&&options.outHeight in 1..8192&&options.outMimeType in listOf("image/jpeg","image/png","image/webp")){"Unsupported artwork"}
        val file=artFile(key);val tmp=File(file.path+".part");try{tmp.writeBytes(bytes);check(tmp.renameTo(file))}finally{tmp.delete()};prefs.edit().putLong("library_revision",prefs.getLong("library_revision",0)+1).apply();return JSONObject().put("stored",true)
    }
    private var ready = false
    private var preparing = false
    private var paused = true
    private var selected = ""
    private var volume = 50
    private var loop = true
    private var generation = 0L
    private var failure: String? = null
    private var timerElapsed: Long? = null
    private val timerTask = Runnable { stopPlayback() }
    private var advert: NsdManager.RegistrationListener? = null
    private var registered = false
    private var advertName = ""
    private var destroyed = false
    private val events = ArrayDeque<JSONObject>()
    private val catalog = mutableMapOf<String,JSONObject>()
    val token: String = Base64.encodeToString(ByteArray(32).also { SecureRandom().nextBytes(it) }, Base64.NO_WRAP or Base64.URL_SAFE)
    private val tracksDir get() = File(filesDir,"host-tracks").apply { mkdirs() }
    override fun onBind(intent: Intent?) = null
    override fun onCreate() {
        super.onCreate()
        prefs = getSharedPreferences("android_host",MODE_PRIVATE)
        if(!prefs.contains("host_id")) prefs.edit().putString("host_id",UUID.randomUUID().toString().replace("-", "")).apply()
        volume=prefs.getInt("volume",50).coerceIn(0,100);loop=prefs.getBoolean("loop",true);selected=prefs.getString("selected","").orEmpty()
        library=HostLibrary(this,this)
        gainDb=prefs.getFloat("gain_db",0f).toDouble();bypass=prefs.getBoolean("bypass",false);eqEnabled=prefs.getBoolean("eq_enabled",false)
        eqLevels=JSONArray(prefs.getString("eq_levels","[0,0,0,0,0]"));playMode=prefs.getString("play_mode",if(loop)"loop"else"once").orEmpty()
        main.postDelayed(statsTask,30000)
        audio=getSystemService(AUDIO_SERVICE) as AudioManager
        focus=AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
            .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
            .setOnAudioFocusChangeListener({ change ->
                if(change!=AudioManager.AUDIOFOCUS_GAIN && ready && !paused) { pause(true); note("Paused for audio focus") }
            },main).build()
        session=MediaSession(this,"Sleep Sounds Android host").apply {
            setCallback(object: MediaSession.Callback() {
                override fun onPlay(){ if(ready)pause(false) else if(selected.isNotBlank())play(selected) }
                override fun onPause(){pause(true)}
                override fun onStop(){stopPlayback()}
                override fun onSeekTo(pos:Long){seek(pos/1000.0)}
            });isActive=true
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel(CHANNEL,"Sleep Sounds host",NotificationManager.IMPORTANCE_LOW))
        startForeground(812,notification())
        try { server=HostHttpServer(this,this).also { it.start() };running=true;advertise();note("Android host ready") }
        catch(error:Exception){ failure="Host could not start: ${error.javaClass.simpleName}";note(failure!!);stopSelf() }
    }
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int { if(intent?.action=="rename")advertise();return START_NOT_STICKY }
    private fun name()=prefs.getString("host_name","Android host").orEmpty()
    fun identity()=JSONObject().put("service","sleep-sounds").put("host_id",prefs.getString("host_id",""))
        .put("name",name()).put("platform","android").put("role","playback-host").put("version",BuildConfig.VERSION_NAME)
    fun note(event:String) { synchronized(events){events.addLast(JSONObject().put("time_ms",System.currentTimeMillis()).put("event",event.take(160)));while(events.size>80)events.removeFirst()};Log.i("SleepSoundsHost",event.take(160)) }
    fun <T> onMain(block:()->T):T {
        if(Looper.myLooper()==Looper.getMainLooper())return block()
        val value=AtomicReference<T>();val error=AtomicReference<Throwable>();val latch=CountDownLatch(1)
        main.post { try { value.set(block()) } catch(e:Throwable){error.set(e)} finally { latch.countDown() } }
        check(latch.await(8,TimeUnit.SECONDS)){"Host is busy"};error.get()?.let { throw it };return value.get()
    }
    private fun audioFile(id:String):File {
        require(id.isNotBlank() && id.length<=200 && id!="." && id!=".." && !id.contains('/') && !id.contains('\\') && id.none { it.code<32 }){"Invalid audio name"}
        val file=File(tracksDir,id)
        require(file.canonicalFile.parentFile==tracksDir.canonicalFile){"Invalid audio path"}
        return file
    }
    private fun metadata(file:File):JSONObject = synchronized(catalog) {
        catalog[file.name]?.takeIf { it.optLong("bytes")==file.length() } ?: run {
            val retriever=MediaMetadataRetriever()
            val data=try {
                retriever.setDataSource(file.absolutePath)
                val duration=(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toDoubleOrNull()?:0.0)/1000
                require(duration>0){"No supported audio stream"}
                JSONObject().put("id",file.name).put("name",file.name.substringBeforeLast('.'))
                    .put("bytes",file.length()).put("duration_seconds",duration)
                    .put("format",file.extension.uppercase()).put("bitrate_kbps",(retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_BITRATE)?.toDoubleOrNull()?:0.0)/1000)
            } finally { retriever.release() }
            catalog[file.name]=data;data
        }
    }
    fun tracks():JSONArray {
        val result=JSONArray()
        tracksDir.listFiles()?.filter { it.isFile && !it.name.startsWith('.') }?.sortedBy { it.name.lowercase() }?.forEach {
            try { result.put(metadata(it)) } catch(_:Exception) { }
        }
        return result
    }
    @Synchronized fun importAudio(name:String,input:InputStream,length:Long):JSONObject {
        val destination=audioFile(name)
        require(destination.extension.lowercase() in listOf("m4a","aac","mp3","flac","wav","ogg","opus","mp4","webm")){"Unsupported audio extension"}
        require(!destination.exists()){"That recording already exists"}
        require(tracksDir.usableSpace>length+128L*1024*1024){"Not enough free space"}
        val temp=File(tracksDir,".${UUID.randomUUID()}.part")
        try {
            temp.outputStream().buffered(65536).use { output ->
                val buffer=ByteArray(65536);var remaining=length
                while(remaining>0){val n=input.read(buffer,0,minOf(buffer.size.toLong(),remaining).toInt());check(n>0){"Upload interrupted"};output.write(buffer,0,n);remaining-=n}
            }
            metadata(temp) // Validate before making the file visible; no re-encoding.
            check(temp.renameTo(destination)){"Could not save recording"}
            synchronized(catalog){catalog.remove(temp.name)}
            prefs.edit().putLong("library_revision",prefs.getLong("library_revision",0)+1).apply()
            note("Audio import completed");return JSONObject().put("track",destination.name).put("id",destination.name).put("stored",true)
        } finally {temp.delete();synchronized(catalog){catalog.remove(temp.name)}}
    }
    private fun persist(){prefs.edit().putInt("volume",volume).putBoolean("loop",loop).putString("selected",selected).apply()}
    private fun position()=if(ready)try{player?.currentPosition?.toDouble()?.div(1000)?:0.0}catch(_:Exception){0.0}else 0.0
    private fun duration()=if(ready)try{player?.duration?.toDouble()?.div(1000)?:0.0}catch(_:Exception){0.0}else 0.0
    private fun acquireFocus(){check(audio.requestAudioFocus(focus)==AudioManager.AUDIOFOCUS_REQUEST_GRANTED){"Another app is using audio"}}
    private fun play(id:String) {
        val file=audioFile(id);require(file.isFile){"Recording not found"}
        account();releaseEffects();generation++;val owner=generation;player?.release();ready=false;preparing=true;paused=false;failure=null;selected=id
        val p=MediaPlayer();player=p
        p.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
        p.setWakeMode(this,PowerManager.PARTIAL_WAKE_LOCK);p.setVolume(volume/100f,volume/100f);p.isLooping=loop
        p.setOnPreparedListener {
            if(owner!=generation)return@setOnPreparedListener
            preparing=false;ready=true
            try { if(timerElapsed?.let { SystemClock.elapsedRealtime()>=it }==true){stopPlayback();return@setOnPreparedListener}
                acquireFocus()
                try{equalizer=android.media.audiofx.Equalizer(0,p.audioSessionId);eqAvailable=true;applyEffects()}catch(_:Exception){releaseEffects();if(eqEnabled){eqEnabled=false;note("Android equalizer unavailable on this output")};applyEffects()}
                if(!paused)p.start();tickAt=SystemClock.elapsedRealtime();update();note("Playback prepared") }
            catch(e:Exception){failure=e.message;paused=true;update()}
        }
        p.setOnErrorListener { _,what,extra ->
            if(owner==generation){failure="Android decoder/output error $what/$extra";preparing=false;ready=false;paused=true;note(failure!!);update()};true
        }
        p.setOnCompletionListener { if(owner==generation){account();if(playMode in listOf("next","shuffle"))next(1)else{paused=true;update();note("Playback ended")}} }
        try {p.setDataSource(file.absolutePath);p.prepareAsync();persist();update();note("Playback requested")}
        catch(e:Exception){preparing=false;paused=true;failure="Could not load recording";p.release();player=null;throw e}
    }
    private fun pause(value:Boolean){
        check(ready || preparing){"Choose a recording first"}
        if(!value && timerElapsed?.let { SystemClock.elapsedRealtime()>=it }==true){stopPlayback();return}
        account();paused=value
        if(ready){if(value)player?.pause()else{acquireFocus();player?.start()}}
        if(value)audio.abandonAudioFocusRequest(focus)
        update();note(if(value)"Playback paused"else"Playback resumed")
    }
    private fun stopPlayback(){account();releaseEffects();generation++;player?.release();player=null;ready=false;preparing=false;paused=true;timerElapsed=null;main.removeCallbacks(timerTask);audio.abandonAudioFocusRequest(focus);update();note("Playback stopped")}
    private fun seek(seconds:Double){require(seconds.isFinite() && seconds>=0 && ready && seconds<=duration()){ "Position unavailable" };player?.seekTo((seconds*1000).toLong(),MediaPlayer.SEEK_CLOSEST);note("Position changed")}
    private fun timer(minutes:Double){require(minutes.isFinite()&&minutes in 0.0..1440.0);main.removeCallbacks(timerTask);timerElapsed=if(minutes==0.0)null else SystemClock.elapsedRealtime()+(minutes*60000).toLong();timerElapsed?.let{main.postDelayed(timerTask,(minutes*60000).toLong())};note("Sleep timer changed")}
    private fun next(delta:Int){val list=tracks();require(list.length()>0);val ids=(0 until list.length()).map{list.getJSONObject(it).getString("id")};val n=if(playMode=="shuffle")ids.filter{it!=selected}.randomOrNull()?:ids.first()else ids[Math.floorMod(ids.indexOf(selected)+delta,ids.size)];play(n);library.played(n,activeProfile,newPlay=true)}
    fun mutate(path:String,body:JSONObject):Any {
        library.mutate(path,body)?.let{return it}
        when(path){
            "/api/play","/api/sleep" -> {val pid=body.optString("profile","none");library.data(pid);account();activeProfile=pid;play(body.getString("track"));library.played(selected,pid,newPlay=true);if(path=="/api/sleep")timer(body.getDouble("minutes"))}
            "/api/select-track"->{val id=body.getString("track");require(audioFile(id).isFile);stopPlayback();selected=id;persist()}
            "/api/next"->next(1)
            "/api/previous"->next(-1)
            "/api/output"->require(body.getString("name")=="android/system"){"Choose Bluetooth/HDMI in Android system settings"}
            "/api/play_mode"->{val mode=body.getString("mode");require(mode in listOf("once","loop","next","shuffle"));playMode=mode;loop=mode=="loop";player?.isLooping=loop;persist();prefs.edit().putString("play_mode",mode).apply()}
            "/api/timer_end"->{val time=body.getString("time");require(Regex("[0-2][0-9]:[0-5][0-9]").matches(time));val parts=time.split(':');require(parts[0].toInt()<24);val now=java.util.Calendar.getInstance();val end=now.clone()as java.util.Calendar;end.set(java.util.Calendar.HOUR_OF_DAY,parts[0].toInt());end.set(java.util.Calendar.MINUTE,parts[1].toInt());end.set(java.util.Calendar.SECOND,0);if(!end.after(now))end.add(java.util.Calendar.DAY_OF_YEAR,1);timer((end.timeInMillis-now.timeInMillis)/60000.0)}
            "/api/track-delete"->{require(prefs.getBoolean("allow_track_deletion",false)&&body.getBoolean("confirm"));val id=body.getString("track");require(id!=selected||(!ready&&!preparing)){"Stop this recording before deleting"};check(audioFile(id).delete());artFile(id).delete();prefs.edit().putLong("library_revision",prefs.getLong("library_revision",0)+1).apply()}
            "/api/normalization"->require(!body.getBoolean("enabled")){"Normalization is not yet ported to Android"}
            "/api/audio-processing"->{
                if(body.has("expected_revision"))check(body.getInt("expected_revision")==revision){"Audio settings changed; reload"}
                val v=body.getJSONObject("settings");require(v.keys().asSequence().all{it in listOf("gain_db","bypass","gain_enabled","eq_enabled","eq_levels")}){"This Android build supports gain and system EQ only"}
                val gain=v.optDouble("gain_db",gainDb);require(gain.isFinite()&&gain in -24.0..0.0){"Android gain must be -24 to 0 dB"}
                val levels=v.optJSONArray("eq_levels")?:eqLevels;require(levels.length()==5&&(0..4).all{levels.getDouble(it).isFinite()&&levels.getDouble(it) in -12.0..12.0})
                val enabled=v.optBoolean("eq_enabled",eqEnabled);require(!enabled||eqAvailable){"Start a track on an EQ-compatible Android output first"}
                gainDb=gain;eqEnabled=enabled;eqLevels=levels;bypass=v.optBoolean("bypass",bypass);applyEffects();revision++
                prefs.edit().putFloat("gain_db",gainDb.toFloat()).putBoolean("bypass",bypass).putBoolean("eq_enabled",eqEnabled).putString("eq_levels",eqLevels.toString()).apply();return config()
            }
            "/api/pause" -> pause(if(body.has("paused"))body.getBoolean("paused")else !paused)
            "/api/stop" -> stopPlayback()
            "/api/seek" -> seek(body.getDouble("seconds"))
            "/api/timer" -> timer(body.getDouble("minutes"))
            "/api/settings" -> {
                require(body.keys().asSequence().all {it in listOf("volume","loop","profile","editor_session","allow_track_deletion","sleep_minutes")}){"This setting is managed by Android and is unavailable here"}
                if(body.has("allow_track_deletion"))prefs.edit().putBoolean("allow_track_deletion",body.getBoolean("allow_track_deletion")).apply()
                if(body.has("sleep_minutes")){val n=body.getInt("sleep_minutes");require(n in 1..1440);prefs.edit().putInt("sleep_minutes",n).apply()}
                if(body.has("volume")){val n=body.get("volume");require(n is Int && n in 0..100);volume=n;applyEffects()}
                if(body.has("loop")){require(body.get("loop")is Boolean);loop=body.getBoolean("loop");player?.isLooping=loop}
                persist();note("Volume/loop changed")
            }
            "/api/host-name" -> {val n=body.getString("name").trim();require(n.length in 1..60 && n.toByteArray(Charsets.UTF_8).size<=60 && n.none {it.code<32});prefs.edit().putString("host_name",n).apply();advertise();update()}
            else -> throw IllegalArgumentException("This feature is not supported by the Android host preview")
        }
        return if(path=="/api/settings")config()else status()
    }
    fun status():JSONObject = JSONObject().put("csrf",token).put("host_name",name()).put("host_id",prefs.getString("host_id",""))
        .put("selected",selected).put("idle",!ready&&!preparing).put("paused",paused).put("starting",preparing)
        .put("position",position()).put("duration",duration()).put("volume",volume).put("loop",loop)
        .put("playback_error",failure?:JSONObject.NULL).put("active_output","android/system")
        .put("platform","android").put("play_mode",playMode).put("normalization",false).put("audio_processing_revision",revision).put("output_ready",true).put("clock_ready",true).put("timezone",java.util.TimeZone.getDefault().id).put("server_time",System.currentTimeMillis()/1000.0).put("library_revision",prefs.getLong("library_revision",0))
        .put("timer_seconds",timerElapsed?.let{maxOf(0L,it-SystemClock.elapsedRealtime())/1000.0}?:JSONObject.NULL)
        .put("capabilities",JSONObject().put("local_playback",true).put("effects",true).put("multiple_outputs",false).put("profiles",true).put("alarms",false).put("remotes",false))
    fun diagnostics():JSONObject = status().apply {remove("csrf");put("platform","Android ${Build.VERSION.RELEASE}");put("model",Build.MODEL);put("version",BuildConfig.VERSION_NAME);put("events",synchronized(events){JSONArray(events.toList())})}
    private fun update(){
        session.setPlaybackState(PlaybackState.Builder().setActions(PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or PlaybackState.ACTION_STOP or PlaybackState.ACTION_SEEK_TO)
            .setState(if(!ready)PlaybackState.STATE_STOPPED else if(paused)PlaybackState.STATE_PAUSED else PlaybackState.STATE_PLAYING,(position()*1000).toLong(),if(paused)0f else 1f).build())
        if(Build.VERSION.SDK_INT<33 || checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)==android.content.pm.PackageManager.PERMISSION_GRANTED)
            getSystemService(NotificationManager::class.java).notify(812,notification())
        else startForeground(812,notification())
    }
    private fun notification():Notification {
        val intent=PendingIntent.getActivity(this,0,Intent(this,MainActivity::class.java),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_media_play).setContentTitle(name()+" · Sleep Sounds")
            .setContentText(if(!paused)"Playing locally"else"Local playback host ready").setContentIntent(intent).setOngoing(true)
            .setStyle(Notification.MediaStyle().setMediaSession(session.sessionToken)).build()
    }
    @Suppress("DEPRECATION") private fun advertise(){
        if(destroyed)return
        val manager=getSystemService(NSD_SERVICE)as NsdManager
        if(advert!=null){if(registered){registered=false;try{manager.unregisterService(advert)}catch(_:Exception){advert=null;advertise()}};return}
        advertName=name()
        val listener=object:NsdManager.RegistrationListener{
            override fun onServiceRegistered(info:NsdServiceInfo){registered=true;if(name()!=advertName)advertise()}
            override fun onRegistrationFailed(info:NsdServiceInfo,code:Int){advert=null;registered=false;note("LAN advertisement unavailable $code")}
            override fun onServiceUnregistered(info:NsdServiceInfo){advert=null;registered=false;if(!destroyed)advertise()}
            override fun onUnregistrationFailed(info:NsdServiceInfo,code:Int){advert=null;registered=false}
        }
        advert=listener
        manager.registerService(NsdServiceInfo().apply{serviceName=advertName;serviceType="_sleep-sounds._tcp.";port=8080;setAttribute("host_id",prefs.getString("host_id","").orEmpty())},NsdManager.PROTOCOL_DNS_SD,listener)
    }
    override fun onDestroy(){
        destroyed=true;running=false;main.removeCallbacksAndMessages(null);server?.close();account();releaseEffects();player?.release();audio.abandonAudioFocusRequest(focus);session.release()
        advert?.let {try{(getSystemService(NSD_SERVICE)as NsdManager).unregisterService(it)}catch(_:Exception){}}
        super.onDestroy()
    }
}
