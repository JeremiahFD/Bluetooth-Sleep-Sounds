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
    @Volatile private var scan=0
    fun cancelScan(){scan++}
    fun show(rows:List<SavedDevices.Device> = store.all()){
        cancelScan()
        val layout=LinearLayout(activity).apply{orientation=LinearLayout.VERTICAL;setPadding(24,8,24,8)}
        val names=rows.map{it.name+(if(store.preferred()==it.key)" ★"else "")}.toTypedArray()
        val list=Spinner(activity).apply{adapter=ArrayAdapter(activity,android.R.layout.simple_spinner_dropdown_item,names);setSelection(maxOf(0,rows.indexOfFirst{it.key==key}))};layout.addView(list)
        val remember=CheckBox(activity).apply{text="Remember as default on this device";isChecked=store.preferred()!=null};layout.addView(remember)
        AlertDialog.Builder(activity).setTitle("Choose sleep device").setView(layout).setPositiveButton("Connect"){_,_->
            rows.getOrNull(list.selectedItemPosition)?.let{store.prefer(if(remember.isChecked)it.key else null);choose(it.key)}
        }.setNeutralButton("Connections & defaults"){_,_->settings()}.setNegativeButton("Cancel",null).show()
    }
    fun startup(budget:ConnectionBudget,onSelectionRequired:()->Unit={},onChosen:(String)->Unit){
        val generation=++scan
        val ownEnabled=hostPrefs.getBoolean("enabled",((activity.getSystemService(Context.UI_MODE_SERVICE) as android.app.UiModeManager).currentModeType==android.content.res.Configuration.UI_MODE_TYPE_TELEVISION))
        if(ownEnabled)try{activity.startForegroundService(Intent(activity,AndroidHostService::class.java))}catch(_:Exception){}
        HostSelection.automatic(store.preferred(),emptyList())?.let{onChosen(it);return}
        Thread({
            val executor=java.util.concurrent.Executors.newFixedThreadPool(3)
            try{
                val known=store.all()
                val pending=known.map{device->executor.submit<Pair<SavedDevices.Device,String>?>{
                    val addresses=if(device.key=="onn"&&ownEnabled)listOf("http://127.0.0.1:8080")else listOf(device.lan,device.alternate).filter{it.isNotBlank()}
                    for(raw in addresses){
                        if(generation!=scan||budget.expired(android.os.SystemClock.elapsedRealtime()))break
                        val address=HostProbe.normalize(raw,device.key=="onn"&&ownEnabled)?:continue
                        val result=HostProbe.read(address,budget,device.identity)?:continue
                        device.identity=result.identity;store.update(device);return@submit device to result.identity
                    };null
                }}
                val discovery=executor.submit<List<HostProbe.Result>>{
                    try{HostDiscovery(activity).find(minOf(budget.deadline,android.os.SystemClock.elapsedRealtime()+5500)).mapNotNull{row->
                        val address=HostProbe.normalize(row.address)?:return@mapNotNull null
                        if(generation!=scan)null else HostProbe.read(address,budget)
                    }}catch(_:Exception){emptyList()}
                }
                val reachable=pending.mapNotNull{try{it.get(maxOf(1,budget.remaining(android.os.SystemClock.elapsedRealtime())),java.util.concurrent.TimeUnit.MILLISECONDS)}catch(_:Exception){null}}.toMutableList()
                val discovered=try{discovery.get(maxOf(1,budget.remaining(android.os.SystemClock.elapsedRealtime())),java.util.concurrent.TimeUnit.MILLISECONDS)}catch(_:Exception){emptyList()}
                if(generation!=scan)return@Thread
                discovered.forEach{result->reachable.add(store.discovered(result) to result.identity)}
                val unique=reachable.distinctBy{it.second}.map{it.first}
                activity.runOnUiThread{
                    if(generation==scan&&!activity.isFinishing&&!activity.isDestroyed){
                        if(unique.size>1){onSelectionRequired();show(unique)}
                        else onChosen(HostSelection.automatic(null,reachable.map{it.first.key to it.second})?:key)
                    }
                }
            }finally{executor.shutdownNow()}
        },"SleepSounds-startup-discovery").start()
    }
    fun settings(){
        val layout=LinearLayout(activity).apply{orientation=LinearLayout.VERTICAL;setPadding(24,8,24,8)}
        val choices=store.all()
        layout.addView(TextView(activity).apply{text="Default sleep device (this installation only)"})
        val preferred=Spinner(activity).apply{adapter=ArrayAdapter(activity,android.R.layout.simple_spinner_dropdown_item,listOf("Ask / automatic")+choices.map{it.name});setSelection(choices.indexOfFirst{it.key==store.preferred()}+1)};layout.addView(preferred)
        val names=choices.map{device->
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
            store.prefer(choices.getOrNull(preferred.selectedItemPosition-1)?.key)
            names.forEach{(device,field)->device.name=field.text.toString().trim();store.update(device)}
            hostPrefs.edit().putString("host_name",own.text.toString().trim()).putBoolean("enabled",enabled.isChecked).apply()
            if(AndroidHostService.running){if(enabled.isChecked)activity.startService(Intent(activity,AndroidHostService::class.java).setAction("rename"))else activity.stopService(Intent(activity,AndroidHostService::class.java))}
            renamed();dialog.dismiss()
        }};dialog.show()
    }
}
