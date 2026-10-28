package local.sleepsounds.controller

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.webkit.*
import android.widget.*
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import java.io.ByteArrayInputStream

/** Named host controller, with optional independent Android playback. */
class MainActivity : Activity() {
    private lateinit var devicePicker: DevicePicker
    private lateinit var offlineTitle:TextView
    private lateinit var progress:ProgressBar
    private val connectionHandler=android.os.Handler(android.os.Looper.getMainLooper())
    @Volatile private var connectionBudget:ConnectionBudget?=null

    private var clearHostHistory=false
    private lateinit var web: WebView
    private lateinit var swipe: SwipeRefreshLayout
    private lateinit var offline: LinearLayout
    private lateinit var errorMessage: TextView
    private var origin = ""
    private var mainFrameFailed = false
    @Volatile private var connectionGeneration = 0
    private var nativeSession = java.util.UUID.randomUUID().toString()
    private var profileConfirmed = false
    private var lastProfile: String? = null
    private var exportOrigin: String? = null
    private var chooser: ValueCallback<Array<Uri>>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        devicePicker=DevicePicker(this,getPreferences(MODE_PRIVATE),::switchDevice,::showServerEditor,{installHostSelector()})
        nativeSession=savedInstanceState?.getString("native_session") ?: nativeSession
        profileConfirmed=savedInstanceState?.getBoolean("profile_confirmed") ?: false
        val night = Color.rgb(9,21,36)
        val root = FrameLayout(this).apply { setBackgroundColor(night) }
        web = WebView(this).apply {
            setBackgroundColor(night)
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.userAgentString += " SleepSoundsAndroid/${BuildConfig.VERSION_NAME} (build ${BuildConfig.VERSION_CODE})"
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            settings.setSupportMultipleWindows(false)
            // Keep WebView locked to the selected Pi origin. No JS bridge or bypasses.
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val uri = request.url
                    if(request.isForMainFrame&&request.hasGesture()&&allowed(Uri.parse(view.url?:""))&&uri.toString()=="sleep-sounds://devices"){
                        connectionGeneration++;connectionBudget=null;devicePicker.cancelScan();devicePicker.show();return true
                    }
                    if (request.isForMainFrame && request.hasGesture() && allowed(Uri.parse(view.url ?: "")) &&
                        uri.toString()=="sleep-sounds://diagnostics") {
                        exportOrigin=origin
                        try { startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                            .setType("application/json").putExtra(Intent.EXTRA_TITLE,"sleep-sounds-diagnostics.json"),102) }
                        catch(_:Exception){Toast.makeText(this@MainActivity,"No document picker available.",Toast.LENGTH_LONG).show()}
                        return true
                    }
                    if (request.isForMainFrame && request.hasGesture() && allowed(Uri.parse(view.url ?: "")) &&
                        uri.toString() in listOf("sleep-sounds://reconnect","sleep-sounds://connections")) {
                        if(uri.host=="connections")devicePicker.settings() else connect(savedAddress())
                        return true
                    }
                    if (request.isForMainFrame && request.hasGesture() && allowed(Uri.parse(view.url ?: "")) &&
                        uri.toString() == "sleep-sounds://android-bluetooth") {
                        try { startActivity(Intent(android.provider.Settings.ACTION_BLUETOOTH_SETTINGS)) }
                        catch(_:android.content.ActivityNotFoundException) { startActivity(Intent(android.provider.Settings.ACTION_SETTINGS)) }
                        return true
                    }
                    if (request.isForMainFrame && request.hasGesture() && allowed(Uri.parse(view.url ?: "")) &&
                        uri.toString() == "sleep-sounds://app-update") {
                        startActivity(Intent(this@MainActivity, UpdateInstallerActivity::class.java).putExtra("origin",origin))
                        return true
                    }
                    // Only a user click in our Pi page can open that same Pi's VNC viewer.
                    if (request.isForMainFrame && request.hasGesture() && allowed(Uri.parse(view.url ?: "")) &&
                        uri.scheme == "vnc" && uri.host == Uri.parse(origin).host && uri.port == 5900 &&
                        uri.userInfo == null && uri.query == null && uri.fragment == null &&
                        (uri.path.isNullOrEmpty() || uri.path == "/")) {
                        try {
                            startActivity(Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE))
                        } catch (_: android.content.ActivityNotFoundException) {
                            Toast.makeText(this@MainActivity, "Install a VNC viewer, or copy the address from Settings.", Toast.LENGTH_LONG).show()
                        } catch (_: SecurityException) {
                            Toast.makeText(this@MainActivity, "The VNC viewer could not be opened. Copy the address from Settings.", Toast.LENGTH_LONG).show()
                        }
                        return true
                    }
                    if(request.isForMainFrame && request.hasGesture() && allowed(Uri.parse(view.url ?: "")) &&
                        !allowed(uri) && uri.scheme in listOf("http","https") && uri.userInfo==null) {
                        try { startActivity(Intent(Intent.ACTION_VIEW,uri).addCategory(Intent.CATEGORY_BROWSABLE)) }
                        catch(_:Exception) { Toast.makeText(this@MainActivity,"No browser could open this link.",Toast.LENGTH_LONG).show() }
                        return true
                    }
                    return !allowed(uri)
                }
                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                    if(allowed(request.url)&&request.url.path=="/ui/native-host.css")return WebResourceResponse("text/css","UTF-8",assets.open("native-host.css"))
                    if (allowed(request.url)) return null
                    return WebResourceResponse("text/plain","UTF-8",403,"Blocked",emptyMap(),ByteArrayInputStream(ByteArray(0)))
                }
                override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) {
                    if(currentPage(Uri.parse(url)))mainFrameFailed = false
                }
                override fun onPageFinished(view: WebView, url: String) {
                    swipe.isRefreshing = false
                    if (!mainFrameFailed && currentPage(Uri.parse(url))) {
                        connectionBudget=null
                        offline.visibility = View.GONE
                        installHostSelector()
                        if(clearHostHistory){web.clearHistory();clearHostHistory=false}
                    }
                }
                override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                    if (request.isForMainFrame && currentPage(request.url)) {
                        mainFrameFailed = true
                        swipe.isRefreshing = false
                        retryPage("Could not load the host page.")
                    }
                }
                override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, response: WebResourceResponse) {
                    if (request.isForMainFrame && currentPage(request.url) && response.statusCode >= 400) {
                        mainFrameFailed = true
                        swipe.isRefreshing = false
                        retryPage("Host page returned ${response.statusCode}.")
                    }
                }
            }
            // Raw APK links use the verified updater, not an unhandled WebView download.
            setDownloadListener { url, _, _, _, _ ->
                val uri=Uri.parse(url)
                if(allowed(uri) && uri.path=="/install/SleepSounds.apk" && uri.query==null && uri.fragment==null)
                    startActivity(Intent(this@MainActivity,UpdateInstallerActivity::class.java).putExtra("origin",origin))
                else Toast.makeText(this@MainActivity,"Use the verified app update button.",Toast.LENGTH_LONG).show()
            }
            webChromeClient = object : WebChromeClient() {
                override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                    if (!allowed(Uri.parse(view.url ?: ""))) return false
                    chooser?.onReceiveValue(null)
                    chooser = callback
                    val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = "*/*"
                        putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.mode == FileChooserParams.MODE_OPEN_MULTIPLE)
                        val accept = params.acceptTypes.filter { it.isNotBlank() }
                        if (accept.isNotEmpty() && accept.all {
                            it == "image/*" || it.endsWith(".png") || it.endsWith(".jpg") ||
                                it.endsWith(".jpeg") || it.endsWith(".webp")
                        }) type = "image/*"
                    }
                    return try { startActivityForResult(intent,101); true }
                    catch (_: android.content.ActivityNotFoundException) { chooser = null; false }
                }
            }
        }
        swipe = SwipeRefreshLayout(this).apply {
            setColorSchemeColors(Color.rgb(168,164,242))
            setProgressBackgroundColorSchemeColor(Color.rgb(27,41,63))
            // Vertical audio-knob gestures must never trigger pull-to-refresh.
            // The same-origin audio route is UI state only; no JavaScript bridge is exposed.
            setOnChildScrollUpCallback { _, _ ->
                web.canScrollVertically(-1) || Uri.parse(web.url ?: "").fragment == "audio"
            }
            setOnRefreshListener { connect(savedAddress()) }
        }
        swipe.addView(web, ViewGroup.LayoutParams(-1,-1))
        root.addView(swipe,FrameLayout.LayoutParams(-1,-1))
        offline = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(28),dp(24),dp(28),dp(24))
            setBackgroundColor(night)
            visibility = View.GONE
        }
        offlineTitle=TextView(this).apply {
            text = "Cannot connect to Sleep Sounds"
            textSize = 21f
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            setPadding(0,0,0,dp(12))
        }
        offline.addView(offlineTitle)
        progress=ProgressBar(this).apply{isIndeterminate=true}
        offline.addView(progress,LinearLayout.LayoutParams(dp(32),dp(32)).apply{gravity=Gravity.CENTER_HORIZONTAL;bottomMargin=dp(16)})
        errorMessage = TextView(this).apply {
            textSize = 14f
            gravity = Gravity.CENTER
            setTextColor(Color.rgb(177,194,213))
            setPadding(0,0,0,dp(22))
        }
        offline.addView(errorMessage)
        offline.addView(Button(this).apply {
            text = "Retry connection"
            setOnClickListener { connect(savedAddress()) }
        }, LinearLayout.LayoutParams(-1,-2))
        offline.addView(Button(this).apply {
            text = "Change server address"
            setOnClickListener { showServerEditor() }
        }, LinearLayout.LayoutParams(-1,-2))
        offline.addView(Button(this).apply{text="Choose sleep device";setOnClickListener{connectionGeneration++;connectionBudget=null;devicePicker.cancelScan();devicePicker.show()}},LinearLayout.LayoutParams(-1,-2))
        offline.addView(Button(this).apply{text="Connections & default device";setOnClickListener{devicePicker.settings()}},LinearLayout.LayoutParams(-1,-2))
        root.addView(offline,FrameLayout.LayoutParams(-1,-1))

        // One inset owner: native root pads system bars and IME; WebView must not pad them again.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
            root.setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                val keyboard = insets.getInsets(WindowInsets.Type.ime())
                view.setPadding(bars.left,bars.top,bars.right,maxOf(bars.bottom,keyboard.bottom))
                WindowInsets.CONSUMED
            }
        } else root.fitsSystemWindows = true
        setContentView(root)
        root.requestApplyInsets()
        if(savedInstanceState==null){
            val budget=ConnectionBudget(android.os.SystemClock.elapsedRealtime());beginConnecting(budget,"Finding sleep devices…")
            devicePicker.startup(budget,onSelectionRequired={connectionBudget=null;progress.visibility=View.GONE;offlineTitle.text="Choose a sleep device"}){key->selectDevice(key,budget)}
        }
        else if(devicePicker.local())startLocalHost()else connect(savedAddress())
    }

    private fun switchDevice(key:String)=selectDevice(key,ConnectionBudget(android.os.SystemClock.elapsedRealtime()))
    private fun selectDevice(key:String,budget:ConnectionBudget){
        devicePicker.cancelScan()
        val selection=++connectionGeneration
        rememberProfile selection@{
            if(selection!=connectionGeneration)return@selection
            devicePicker.save();devicePicker.activate(key)
            lastProfile=getPreferences(MODE_PRIVATE).getString("last_profile",null);profileConfirmed=false;nativeSession=java.util.UUID.randomUUID().toString()
            origin="";web.stopLoading();clearHostHistory=true
            if(devicePicker.local())startLocalHost(budget)else connect(savedAddress(),budget)
        }
    }
    private fun startLocalHost(budget:ConnectionBudget=ConnectionBudget(android.os.SystemClock.elapsedRealtime())){
        val prefs=getSharedPreferences("android_host",MODE_PRIVATE)
        if(!prefs.contains("host_name"))prefs.edit().putString("host_name",devicePicker.name).apply()
        try{startForegroundService(Intent(this,AndroidHostService::class.java))}catch(_:Exception){showOffline("Open this app to start its local playback host.");return}
        beginConnecting(budget,"Starting local playback host…")
        val generation=connectionGeneration
        connectionHandler.post(object:Runnable{override fun run(){
            if(isFinishing||isDestroyed||generation!=connectionGeneration||!devicePicker.local())return
            if(AndroidHostService.running){getPreferences(MODE_PRIVATE).edit().putString("server","http://127.0.0.1:8080").putString("lan_secondary","").apply();connect("http://127.0.0.1:8080",budget)}
            else if(!budget.expired(android.os.SystemClock.elapsedRealtime()))connectionHandler.postDelayed(this,200)
            else showOffline("Local host did not start within 20 seconds.")
        }})
    }
    private fun dp(n: Int) = (n * resources.displayMetrics.density + 0.5f).toInt()
    private fun savedAddress():String {
        if(devicePicker.local())return "http://127.0.0.1:8080"
        val prefs=getPreferences(MODE_PRIVATE)
        return prefs.getString("server", "").orEmpty()
    }
    private fun savedLanFallback(primary:String=savedAddress()):String =
        getPreferences(MODE_PRIVATE).getString("lan_secondary", "").orEmpty()
    private fun allowed(uri: Uri) = (uri.scheme == "http" || uri.scheme == "https") && "${uri.scheme}://${uri.encodedAuthority}" == origin
    private fun currentPage(uri:Uri)=allowed(uri)&&
        (uri.getQueryParameter("native_attempt")?.let{it==connectionGeneration.toString()}!=false)&&
        (connectionBudget?.expired(android.os.SystemClock.elapsedRealtime())!=true)
    private fun showOffline(message:String){mainFrameFailed=true;connectionBudget=null;offlineTitle.text="Cannot connect to Sleep Sounds";progress.visibility=View.GONE;errorMessage.text=message;offline.visibility=View.VISIBLE;swipe.isRefreshing=false}
    private fun beginConnecting(budget:ConnectionBudget,message:String){
        connectionBudget=budget;offlineTitle.text="Connecting to "+devicePicker.name;errorMessage.text=message;progress.visibility=View.VISIBLE;offline.visibility=View.VISIBLE
        val generation=connectionGeneration
        connectionHandler.postDelayed({if(generation==connectionGeneration&&connectionBudget===budget){devicePicker.cancelScan();web.stopLoading();showOffline("No connection after 20 seconds. Retry or choose another sleep device.")}},maxOf(1,budget.remaining(android.os.SystemClock.elapsedRealtime())))
    }
    private fun retryPage(reason:String){
        val budget=connectionBudget
        if(budget!=null&&!budget.expired(android.os.SystemClock.elapsedRealtime())){
            val generation=connectionGeneration
            errorMessage.text="Still connecting…"
            connectionHandler.postDelayed({if(generation==connectionGeneration&&connectionBudget===budget)connect(savedAddress(),budget)},400)
        }else showOffline(reason+" Retry or choose another sleep device.")
    }
    private fun installHostSelector(){
        if(!::web.isInitialized||!allowed(Uri.parse(web.url?:"")))return
        val js="window.__sleepHostLabel="+org.json.JSONObject.quote(devicePicker.name)+";"+assets.open("native-host.js").bufferedReader().use{it.readText()}
        web.evaluateJavascript(js,null)
    }

    private fun normalizeAddress(raw:String, mesh:Boolean=false):String? {
        val text=raw.trim();val explicitScheme=text.contains("://")
        val uri=Uri.parse(if(explicitScheme)text else "http://$text");val host=uri.host.orEmpty().lowercase()
        val octets=host.split('.').mapNotNull { it.toIntOrNull() }
        val ipv4=host.matches(Regex("[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+")) && octets.size==4 && octets.all { it in 0..255 } && host==octets.joinToString(".")
        val local=ipv4 && host=="127.0.0.1" && devicePicker.local() && AndroidHostService.running
        val lan=ipv4 && (octets[0]==10 || (octets[0]==192 && octets[1]==168) || (octets[0]==172 && octets[1] in 16..31))
        val tail=ipv4 && octets[0]==100 && octets[1] in 64..127
        val hostname=host.matches(Regex("[a-z0-9-]+(?:\\.[a-z0-9-]+)*\\.(?:local|ts\\.net)"))
        if(uri.scheme !in listOf("http","https") || uri.userInfo!=null ||
            !(if(mesh)tail || hostname && host.endsWith(".ts.net") else lan || local || hostname && host.endsWith(".local")) ||
            (uri.port!=-1 && uri.port !in 1..65535) || uri.query!=null || uri.fragment!=null ||
            (!uri.path.isNullOrEmpty() && uri.path!="/"))return null
        val port=if(uri.port==-1 && !explicitScheme)8080 else uri.port
        return "${uri.scheme}://$host"+(if(port==-1)"" else ":$port")
    }
    private fun rememberProfile(done:()->Unit) {
        val sourceOrigin=origin;val sourceKey=devicePicker.key;val sourceSession=nativeSession
        if(::web.isInitialized && allowed(Uri.parse(web.url ?: ""))) {
            web.evaluateJavascript("JSON.stringify({profile:localStorage.getItem('sleep-profile-id'),confirmed:sessionStorage.getItem('sleep-profile-confirmed')})") { encoded ->
                if(origin!=sourceOrigin||devicePicker.key!=sourceKey||nativeSession!=sourceSession)return@evaluateJavascript
                try { val data=org.json.JSONObject(org.json.JSONArray("[$encoded]").optString(0));val value=data.optString("profile")
                    profileConfirmed=data.optString("confirmed")==nativeSession
                    if(value=="none" || value.matches(Regex("[a-f0-9]{16}"))) {
                        lastProfile=value;getPreferences(MODE_PRIVATE).edit().putString("last_profile",value).apply()
                    }
                } catch(_:Exception){}
                done()
            }
        } else done()
    }
    private fun connect(raw:String,budget:ConnectionBudget=ConnectionBudget(android.os.SystemClock.elapsedRealtime())){
        val primary=normalizeAddress(raw)
        val expected=getPreferences(MODE_PRIVATE).getString("host_id",null)
        if(primary==null&&expected==null){showOffline("Choose a sleep device or enter its LAN address in Connections.");return}
        val lan=listOfNotNull(primary,normalizeAddress(savedLanFallback())).distinct()
        val mesh=HostProbe.normalize(getPreferences(MODE_PRIVATE).getString("mesh","").orEmpty())
        val generation=++connectionGeneration
        beginConnecting(budget,"Checking LAN, then configured mesh…")
        rememberProfile {
            Thread({
                var found:HostProbe.Result?=null;var searched=false
                while(!budget.expired(android.os.SystemClock.elapsedRealtime())&&generation==connectionGeneration&&connectionBudget===budget){
                    for(address in lan){if(generation!=connectionGeneration)break;found=HostProbe.read(address,budget,expected);if(found!=null)break}
                    if(found==null&&mesh!=null)found=HostProbe.read(mesh,budget,expected)
                    if(found==null&&expected!=null&&!searched&&getPreferences(MODE_PRIVATE).getBoolean("discovery",true)){
                        searched=true
                        val nearby=try{HostDiscovery(this).find(minOf(budget.deadline,android.os.SystemClock.elapsedRealtime()+4500))}catch(_:Exception){emptyList()}
                        for(row in nearby){val address=HostProbe.normalize(row.address)?:continue;found=HostProbe.read(address,budget,expected);if(found!=null)break}
                    }
                    if(found!=null)break
                    if(!budget.expired(android.os.SystemClock.elapsedRealtime()))Thread.sleep(minOf(400L,budget.remaining(android.os.SystemClock.elapsedRealtime())))
                }
                runOnUiThread {
                    if(generation!=connectionGeneration||connectionBudget!==budget||isFinishing||isDestroyed)return@runOnUiThread
                    val result=found
                    if(result==null){showOffline("No connection after 20 seconds. Your selected host was kept; retry or choose another device.");return@runOnUiThread}
                    chooser?.onReceiveValue(null);chooser=null;origin=result.address
                    getPreferences(MODE_PRIVATE).edit().putString("host_id",result.identity).apply()
                    devicePicker.store.get(devicePicker.key)?.let{it.identity=result.identity;if(!devicePicker.local()&&it.lan!=result.address){it.alternate=it.lan;it.lan=result.address};devicePicker.store.update(it)}
                    mainFrameFailed=false
                    val profile=lastProfile?:getPreferences(MODE_PRIVATE).getString("last_profile",null)
                    val query=if(profile!=null&&(profile=="none"||profile.matches(Regex("[a-f0-9]{16}"))))"?native_profile=$profile&native_session=$nativeSession"+(if(profileConfirmed)"&native_confirmed=1"else "")else "?native_session=$nativeSession"
                    web.loadUrl("$origin/ui/$query&native_attempt=$generation")
                }
            },"SleepSounds-host-connect").start()
        }
    }
    private fun showServerEditor() {
        val layout=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(dp(20),0,dp(20),0) }
        val lan=EditText(this).apply { setSingleLine(true);setText(savedAddress());hint="Primary LAN address (Ethernet)";contentDescription="LAN server address" }
        val alternate=EditText(this).apply { setSingleLine(true);setText(savedLanFallback());hint="Alternate LAN address (Wi-Fi)";contentDescription="Alternate LAN server address" }
        val mesh=EditText(this).apply { setSingleLine(true);setText(getPreferences(MODE_PRIVATE).getString("mesh",""));hint="Optional mesh address";contentDescription="Mesh server address" }
        layout.addView(lan);layout.addView(alternate);layout.addView(mesh)
        val discovery=CheckBox(this).apply { text="Discover hosts on this network";isChecked=getPreferences(MODE_PRIVATE).getBoolean("discovery",false) }
        val find=Button(this).apply { text="Find nearby hosts";isEnabled=discovery.isChecked }
        val discoveryStatus=TextView(this)
        layout.addView(discovery);layout.addView(find);layout.addView(discoveryStatus)
        discovery.setOnCheckedChangeListener { _,checked ->
            find.isEnabled=checked
            getPreferences(MODE_PRIVATE).edit().putBoolean("discovery",checked).apply()
        }
        var editorOpen=true
        find.setOnClickListener {
            find.isEnabled=false;discoveryStatus.text="Searching this LAN…"
            Thread({
                var error=false
                val hosts=try { HostDiscovery(this).find().filter { normalizeAddress(it.address)!=null } } catch(_:Exception) { error=true;emptyList() }
                runOnUiThread {
                    if(!editorOpen || isFinishing || isDestroyed)return@runOnUiThread
                    find.isEnabled=discovery.isChecked
                    discoveryStatus.text=if(error)"Discovery unavailable. Use a manual address." else if(hosts.isEmpty())"No hosts found. Check the same LAN or use a manual address." else "Select a host; Connect verifies its identity."
                    if(hosts.isNotEmpty())AlertDialog.Builder(this).setTitle("Nearby Sleep Sounds hosts")
                        .setItems(hosts.map { "${it.name}\n${it.address}" }.toTypedArray()) { _,index -> lan.setText(hosts[index].address) }
                        .setNegativeButton("Cancel",null).show()
                }
            },"SleepSounds-LAN-discovery").start()
        }
        val dialog=AlertDialog.Builder(this).setTitle("Host connections")
            .setMessage("Try primary LAN, alternate LAN, then this host's Tailscale address. Ethernet and Wi-Fi have separate reserved IPs. Tailscale must already be connected on both devices.")
            .setView(layout).setNegativeButton("Cancel",null).setPositiveButton("Connect",null)
            .setNeutralButton("Forget host") { _,_->
                AlertDialog.Builder(this).setTitle("Forget host identity?").setMessage("Only the remembered identity and selected profile on this phone are cleared. The host's data is kept.")
                    .setNegativeButton("Cancel",null).setPositiveButton("Forget") { _,_->getPreferences(MODE_PRIVATE).edit().remove("host_id").remove("last_profile").apply();lastProfile=null;profileConfirmed=false }.show()
            }.create()
        dialog.setOnDismissListener { editorOpen=false }
        dialog.setOnShowListener { dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            val primary=normalizeAddress(lan.text.toString());val secondLan=alternate.text.toString().trim();val meshValue=mesh.text.toString().trim()
            if(primary==null)lan.error="Use a LAN address"
            else if(secondLan.isNotEmpty() && normalizeAddress(secondLan)==null)alternate.error="Use a private LAN address"
            else if(meshValue.isNotEmpty() && normalizeAddress(meshValue,true)==null)mesh.error="Use a 100.64–127.x.x address or .ts.net hostname"
            else {getPreferences(MODE_PRIVATE).edit().putString("lan_secondary",if(secondLan.isEmpty())"" else normalizeAddress(secondLan)).putString("mesh",if(meshValue.isEmpty())"" else normalizeAddress(meshValue,true)).apply();dialog.dismiss();connect(primary)}
        } }
        dialog.show()
    }
    override fun onSaveInstanceState(out:Bundle) { out.putString("native_session",nativeSession);out.putBoolean("profile_confirmed",profileConfirmed);super.onSaveInstanceState(out) }
    override fun onPause() { if(::web.isInitialized)rememberProfile { devicePicker.save() };super.onPause() }

    @Deprecated("Uses the platform document picker")
    override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?) {
        super.onActivityResult(requestCode,resultCode,data)
        if(requestCode==102) {
            val target=data?.data;val source=exportOrigin;exportOrigin=null
            if(resultCode==RESULT_OK && target!=null && source!=null)exportDiagnostics(source,target)
        }
        if (requestCode == 101) {
            val selected = if (resultCode == RESULT_OK) {
                val uris = mutableListOf<Uri>()
                data?.data?.let { uris.add(it) }
                data?.clipData?.let { clips ->
                    for (i in 0 until clips.itemCount) clips.getItemAt(i).uri?.let { uri ->
                        if (!uris.contains(uri)) uris.add(uri)
                    }
                }
                uris.takeIf { it.isNotEmpty() }?.toTypedArray()
            } else null
            chooser?.onReceiveValue(selected)
            chooser = null
        }
    }

    private fun exportDiagnostics(source:String,target:Uri) {
        Thread({
            try {
                val c=java.net.URL("$source/api/diagnostics-export").openConnection() as java.net.HttpURLConnection
                c.connectTimeout=5000;c.readTimeout=8000;c.instanceFollowRedirects=false
                val raw=try {
                    require(c.responseCode==200)
                    c.inputStream.use { input -> val out=java.io.ByteArrayOutputStream();val buffer=ByteArray(4096)
                        while(out.size()<=262144){val n=input.read(buffer);if(n<0)break;out.write(buffer,0,n)};out.toByteArray() }
                } finally { c.disconnect() }
                require(raw.size<=262144);org.json.JSONObject(String(raw,Charsets.UTF_8))
                contentResolver.openOutputStream(target,"wt").use { output -> requireNotNull(output);output.write(raw) }
                runOnUiThread {Toast.makeText(this,"Diagnostics exported.",Toast.LENGTH_LONG).show()}
            } catch(_:Exception) { runOnUiThread {Toast.makeText(this,"Diagnostics could not be exported. Try again when the host is reachable.",Toast.LENGTH_LONG).show()} }
        },"SleepSounds-diagnostics-export").start()
    }

    @Deprecated("WebView history is the app's page stack")
    override fun onBackPressed() {
        if (!::web.isInitialized || !allowed(Uri.parse(web.url ?: ""))) {
            super.onBackPressed()
            return
        }
        web.evaluateJavascript("(function(){if(document.querySelector('dialog[open]')){window.dispatchEvent(new Event('sleep-back'));return true}return false})()") { handled ->
            if (handled != "true") {
                if (web.canGoBack()) web.goBack() else finish()
            }
        }
    }

    override fun onDestroy() {
        connectionGeneration++;connectionBudget=null;devicePicker.cancelScan();connectionHandler.removeCallbacksAndMessages(null)
        chooser?.onReceiveValue(null)
        web.destroy()
        super.onDestroy()
    }

}
