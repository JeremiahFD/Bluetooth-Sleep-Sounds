package local.sleepsounds.controller

import android.os.SystemClock
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

object HostProbe {
    data class Result(val identity:String,val name:String,val address:String)
    fun normalize(raw:String,local:Boolean=false):String?=try{
        val text=raw.trim();val explicit=text.contains("://");val u=URI(if(explicit)text else "http://$text")
        val host=u.host?.lowercase().orEmpty();val nums=host.split('.').mapNotNull{it.toIntOrNull()}
        val ipv4=nums.size==4&&nums.all{it in 0..255}&&host==nums.joinToString(".")
        val privateIp=ipv4&&(nums[0]==10||(nums[0]==192&&nums[1]==168)||(nums[0]==172&&nums[1]in 16..31)||(nums[0]==100&&nums[1]in 64..127)||(local&&host=="127.0.0.1"))
        val dns=host.matches(Regex("[a-z0-9-]+(?:\\.[a-z0-9-]+)*\\.(?:local|ts\\.net)"))
        if(u.scheme !in listOf("http","https")||u.userInfo!=null||u.query!=null||u.fragment!=null||u.path !in listOf("","/")||(!privateIp&&!dns)||u.port !in -1..65535||u.port==0)null
        else "${u.scheme}://$host"+(if(u.port>0)":${u.port}"else if(!explicit)":8080"else "")
    }catch(_:Exception){null}
    fun read(address:String,budget:ConnectionBudget,expected:String?=null):Result? {
        if(budget.expired(SystemClock.elapsedRealtime()))return null
        var c:HttpURLConnection?=null
        return try {
            c=URL("$address/api/identity").openConnection()as HttpURLConnection
            c.connectTimeout=budget.timeout(SystemClock.elapsedRealtime());c.readTimeout=budget.timeout(SystemClock.elapsedRealtime());c.instanceFollowRedirects=false
            if(c.responseCode!=200)return null
            val bytes=c.inputStream.use{input->val out=java.io.ByteArrayOutputStream();val buf=ByteArray(512)
                while(out.size()<=4096&&!budget.expired(SystemClock.elapsedRealtime())){val n=input.read(buf);if(n<0)break;out.write(buf,0,n)};out.toByteArray()}
            if(bytes.size>4096||budget.expired(SystemClock.elapsedRealtime()))return null
            val j=JSONObject(String(bytes,Charsets.UTF_8));val id=j.optString("host_id")
            if(j.optString("service")!="sleep-sounds"||!id.matches(Regex("[a-f0-9]{32}"))||(expected!=null&&expected!=id))null
            else Result(id,j.optString("name",j.optString("host_name","Sleep device")).take(60),address)
        }catch(_:Exception){null}finally{c?.disconnect()}
    }
}
