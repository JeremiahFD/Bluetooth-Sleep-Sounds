package local.sleepsounds.controller

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.os.Build
import android.widget.*

/** Native device choices remain usable on a phone or a TV remote, even when a host is offline. */
class DevicePicker(private val activity: Activity, private val legacy: SharedPreferences,
                   private val choose: (String)->Unit, private val connection: ()->Unit,
                   private val renamed: ()->Unit) {
    val store=SavedDevices(activity,legacy)
    var key=store.selected();private set
    val name get()=store.get(key)?.name ?: "Select device"
    private val hostPrefs get()=activity.getSharedPreferences("android_host",Context.MODE_PRIVATE)
    fun local()=key=="onn" && hostPrefs.getBoolean("enabled",((activity.getSystemService(Context.UI_MODE_SERVICE) as android.app.UiModeManager).currentModeType==android.content.res.Configuration.UI_MODE_TYPE_TELEVISION))
    fun save(){
        val device=store.get(key) ?: return
        if(!local()){device.lan=legacy.getString("server",device.lan).orEmpty();device.alternate=legacy.getString("lan_secondary",device.alternate).orEmpty()}
        device.mesh=legacy.getString("mesh",device.mesh).orEmpty();device.identity=legacy.getString("host_id",null)
        device.profile=legacy.getString("last_profile",null);device.discovery=legacy.getBoolean("discovery",true);store.update(device)
    }
    fun activate(newKey:String){
        store.select(newKey);key=newKey;val device=requireNotNull(store.get(key))
        val edit=legacy.edit().putString("server",device.lan).putString("lan_secondary",device.alternate)
            .putString("mesh",device.mesh).putBoolean("discovery",device.discovery).remove("host_id").remove("last_profile")
        device.identity?.let{edit.putString("host_id",it)};device.profile?.let{edit.putString("last_profile",it)};edit.apply()
    }
    fun show(rows:List<SavedDevices.Device> = store.all()){AlertDialog.Builder(activity).setTitle("Select device")
        .setItems(rows.map{it.name}.toTypedArray()){_,i->choose(rows[i].key)}
        .setNeutralButton("Device settings"){_,_->settings()}.setNegativeButton("Cancel",null).show()}
    /** Startup checks identities, not saved names or a successful TCP connection. */
    fun startup(){
        val ownEnabled=hostPrefs.getBoolean("enabled",((activity.getSystemService(Context.UI_MODE_SERVICE) as android.app.UiModeManager).currentModeType==android.content.res.Configuration.UI_MODE_TYPE_TELEVISION))
        if(ownEnabled)try{activity.startForegroundService(Intent(activity,AndroidHostService::class.java))}catch(_:Exception){}
        Thread({
            val executor=java.util.concurrent.Executors.newFixedThreadPool(2)
            try{
                val checks=store.all().map{device->executor.submit<Pair<SavedDevices.Device,String>?>{
                    val addresses=if(device.key=="onn"&&ownEnabled)listOf("http://127.0.0.1:8080")else listOf(device.lan,device.alternate,device.mesh).filter{it.isNotBlank()}.distinct()
                    for(address in addresses){
                        var connection:java.net.HttpURLConnection?=null
                        try{
                            val uri=android.net.Uri.parse(address)
                            if(uri.scheme!="http"||!uri.host.orEmpty().matches(Regex("[0-9.]+"))||uri.userInfo!=null)continue
                            connection=java.net.URL(address.trimEnd('/')+"/api/identity").openConnection()as java.net.HttpURLConnection
                            connection.connectTimeout=900;connection.readTimeout=900;connection.instanceFollowRedirects=false
                            if(connection.responseCode!=200)continue
                            val bytes=connection.inputStream.use{input->val out=java.io.ByteArrayOutputStream();val buf=ByteArray(512)
                                while(out.size()<=4096){val n=input.read(buf);if(n<0)break;out.write(buf,0,n)};out.toByteArray()};if(bytes.size>4096)continue
                            val info=org.json.JSONObject(String(bytes,Charsets.UTF_8));val identity=info.optString("host_id")
                            if(info.optString("service")=="sleep-sounds"&&identity.matches(Regex("[a-f0-9]{32}"))&&(device.identity.isNullOrBlank()||device.identity==identity))return@submit device to identity
                        }catch(_:Exception){}finally{connection?.disconnect()}
                    };null
                }}
                val reachable=checks.mapNotNull{try{it.get(6,java.util.concurrent.TimeUnit.SECONDS)}catch(_:Exception){null}}.distinctBy{it.second}.map{it.first}
                activity.runOnUiThread{
                    if(!activity.isFinishing&&!activity.isDestroyed){
                        if(reachable.size>1)show(reachable)
                        else choose(reachable.firstOrNull()?.key?:key)
                    }
                }
            }finally{executor.shutdownNow()}
        },"SleepSounds-startup-host-check").start()
    }
    fun settings(){
        val layout=LinearLayout(activity).apply{orientation=LinearLayout.VERTICAL;setPadding(24,8,24,8)}
        val names=store.all().map{device->
            layout.addView(TextView(activity).apply{text=device.name+" name"})
            val field=EditText(activity).apply{setSingleLine(true);setText(device.name)};layout.addView(field);device to field
        }
        layout.addView(TextView(activity).apply{text="This installation / local host name"})
        val own=EditText(activity).apply{setSingleLine(true);setText(hostPrefs.getString("host_name",if(((activity.getSystemService(Context.UI_MODE_SERVICE) as android.app.UiModeManager).currentModeType==android.content.res.Configuration.UI_MODE_TYPE_TELEVISION))"Android host"else Build.MODEL))};layout.addView(own)
        val enabled=CheckBox(activity).apply{text="Enable local playback host on this device";isChecked=hostPrefs.getBoolean("enabled",((activity.getSystemService(Context.UI_MODE_SERVICE) as android.app.UiModeManager).currentModeType==android.content.res.Configuration.UI_MODE_TYPE_TELEVISION))};layout.addView(enabled)
        layout.addView(Button(activity).apply{text="Selected device connection";setOnClickListener{connection()}})
        val dialog=AlertDialog.Builder(activity).setTitle("Device settings").setView(layout).setNegativeButton("Cancel",null).setPositiveButton("Save",null).create()
        dialog.setOnShowListener{dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener{
            val invalid=(names.map{it.second}+own).firstOrNull{it.text.toString().trim().let{v->v.length !in 1..60 || v.any{c->c.code<32}}}
            if(invalid!=null){invalid.error="Use a name from 1 to 60 characters";return@setOnClickListener}
            if(own.text.toString().trim().toByteArray(Charsets.UTF_8).size>60){own.error="Use a shorter local host name";return@setOnClickListener}
            names.forEach{(device,field)->device.name=field.text.toString().trim();store.update(device)}
            hostPrefs.edit().putString("host_name",own.text.toString().trim()).putBoolean("enabled",enabled.isChecked).apply()
            if(AndroidHostService.running){if(enabled.isChecked)activity.startService(Intent(activity,AndroidHostService::class.java).setAction("rename"))else activity.stopService(Intent(activity,AndroidHostService::class.java))}
            renamed();dialog.dismiss()
        }};dialog.show()
    }
}
