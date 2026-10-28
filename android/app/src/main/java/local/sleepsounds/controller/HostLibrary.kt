package local.sleepsounds.controller

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Host-local durable library. Never reads another host's profiles or audio. */
class HostLibrary(context:Context, private val host:AndroidHostService) {
    private val prefs=context.getSharedPreferences("host_library",Context.MODE_PRIVATE)
    private var state=JSONObject(prefs.getString("state",null)?:"{}")
    init {
        if(!state.has("profiles")) {
            state.put("profiles",JSONObject().put("none",newProfile("None"))).put("enabled",false)
                .put("metadata",JSONObject()).put("tags",JSONArray()).put("categories",JSONArray()).put("posts",JSONArray()).put("revision",0)
            listOf("Rain","Thunder","Wind","Forest","Ocean","White noise","Pink noise","Brown noise","Night","Car").forEach { state.getJSONArray("tags").put(JSONObject().put("id",id()).put("name",it)) }
            listOf("weather","nature","water","noise","home","travel","music","tones").forEach { state.getJSONArray("categories").put(JSONObject().put("id",it).put("name",it.replaceFirstChar{c->c.uppercase()}).put("picture",it)) }
            save()
        }
    }
    private fun id()=UUID.randomUUID().toString().replace("-","").take(16)
    private fun newProfile(name:String)=JSONObject().put("name",name).put("preferences",JSONObject()).put("favorites",JSONObject()).put("ratings",JSONObject()).put("stats",JSONObject())
    private fun save(){check(prefs.edit().putString("state",state.toString()).commit()){"Could not save host library"}}
    private fun text(value:String,max:Int):String {val v=value.trim();require(v.length<=max&&v.none{it.code<32&&it!='\n'&&it!='\t'}){"Text is too long or contains control characters"};return v}
    private fun profile(pid:String):JSONObject=state.getJSONObject("profiles").optJSONObject(pid)?:throw IllegalArgumentException("That profile is no longer available")
    private fun effective(pid:String)=if(state.optBoolean("enabled"))pid else "none"
    private fun objects(a:JSONArray)=(0 until a.length()).map{a.getJSONObject(it)}
    private fun catalog():JSONObject=JSONObject().put("revision",state.getInt("revision")).put("tags",state.getJSONArray("tags")).put("categories",state.getJSONArray("categories"))
    fun profiles():JSONObject=JSONObject().put("enabled",state.getBoolean("enabled")).put("profiles",JSONArray(state.getJSONObject("profiles").keys().asSequence().map{JSONObject().put("id",it).put("name",profile(it).getString("name"))}.toList()))
    fun data(pid:String):JSONObject=JSONObject(profile(pid).toString()).put("id",pid)
    fun tracks(pid:String):JSONArray {
        val p=profile(effective(pid));val profiles=state.getJSONObject("profiles")
        return JSONArray(objects(host.tracks()).map { raw ->
            val t=JSONObject(raw.toString());val key=t.getString("id")
            val info=state.getJSONObject("metadata").optJSONObject(key)?:JSONObject().put("tags",JSONArray()).put("categories",JSONArray())
            if(info.optString("title").isNotBlank())t.put("name",info.getString("title"))
            val names=JSONArray();val ratings=JSONArray();var sum=0.0;var count=0
            profiles.keys().forEach { pid2 -> val other=profile(pid2)
                if(other.getJSONObject("favorites").optBoolean(key))names.put(other.getString("name"))
                val rating=other.getJSONObject("ratings").optInt(key,0)
                if(rating>0){sum+=rating;count++;ratings.put(JSONObject().put("profile",pid2).put("name",other.getString("name")).put("rating",rating))}
            }
            t.put("metadata",info).put("favorite",p.getJSONObject("favorites").optBoolean(key)).put("favorited_by",names)
                .put("my_rating",p.getJSONObject("ratings").opt(key)?:JSONObject.NULL).put("rating",if(count>0)sum/count else JSONObject.NULL)
                .put("rating_count",count).put("ratings",ratings)
                .put("artwork",host.artworkUrl(key)?:JSONObject.NULL)
        })
    }
    private fun track(key:String,pid:String):JSONObject=objects(tracks(pid)).firstOrNull{it.getString("id")==key}?:throw IllegalArgumentException("Track not found")
    private fun stats(key:String,pid:String):JSONObject {
        val own=profile(pid).getJSONObject("stats").optJSONObject(key)?:JSONObject();var plays=0;var seconds=0.0
        state.getJSONObject("profiles").keys().forEach {val s=profile(it).getJSONObject("stats").optJSONObject(key);plays+=s?.optInt("play_count")?:0;seconds+=s?.optDouble("play_time_seconds",0.0)?:0.0}
        return JSONObject().put("play_count",plays).put("play_time_seconds",seconds).put("profile_play_count",own.optInt("play_count")).put("profile_play_time_seconds",own.optDouble("play_time_seconds",0.0))
    }
    @Synchronized fun played(key:String,pid:String,seconds:Double=0.0,newPlay:Boolean=false) {
        val p=state.getJSONObject("profiles").optJSONObject(effective(pid))?:profile("none");val s=p.getJSONObject("stats").optJSONObject(key)?:JSONObject()
        s.put("play_count",s.optInt("play_count")+if(newPlay)1 else 0).put("play_time_seconds",s.optDouble("play_time_seconds",0.0)+seconds)
        p.getJSONObject("stats").put(key,s);save()
    }
    @Synchronized fun get(path:String,uri:Uri):Any? {
        val pid=uri.getQueryParameter("profile")?:"none"
        return when(path){
            "/api/tracks"->tracks(pid)
            "/api/profiles"->profiles()
            "/api/profile-data"->data(effective(pid))
            "/api/library-catalog"->catalog()
            "/api/library-summary"->JSONObject().put("duration_seconds",objects(tracks(pid)).sumOf{it.optDouble("duration_seconds",0.0)}).put("play_time_seconds",objects(tracks(pid)).sumOf{stats(it.getString("id"),effective(pid)).getDouble("play_time_seconds")})
            "/api/track-details"->{val key=uri.getQueryParameter("track").orEmpty();val t=track(key,pid);JSONObject().put("audio",t).put("stats",stats(key,effective(pid))).put("favorited_by",t.getJSONArray("favorited_by"))}
            "/api/public-profile"->{val p=profile(pid);val all=objects(tracks(pid));JSONObject().put("id",pid).put("name",p.getString("name")).put("favorites",JSONArray(all.filter{p.getJSONObject("favorites").optBoolean(it.getString("id"))})).put("ratings",JSONArray(all.filter{p.getJSONObject("ratings").has(it.getString("id"))}.map{JSONObject().put("id",it.getString("id")).put("name",it.getString("name")).put("rating",p.getJSONObject("ratings").getInt(it.getString("id")))})).put("stats",JSONObject().put("play_count",all.sumOf{stats(it.getString("id"),pid).getInt("profile_play_count")}).put("play_time_seconds",all.sumOf{stats(it.getString("id"),pid).getDouble("profile_play_time_seconds")}))}
            "/api/feedback","/api/track-comments"->posts(if(path.endsWith("track-comments"))uri.getQueryParameter("track").orEmpty() else "")
            "/api/upload-result"->JSONObject().put("complete",false)
            else->null
        }
    }
    private fun posts(track:String):JSONObject {
        val all=objects(state.getJSONArray("posts")).filter{it.optString("track")==track}
        fun display(p:JSONObject)=JSONObject(p.toString()).put("name",state.getJSONObject("profiles").optJSONObject(p.getString("profile"))?.optString("name")?:"Deleted profile")
        return JSONObject().put("posts",JSONArray(all.filter{it.isNull("parent")}.map{p->display(p).put("replies",JSONArray(all.filter{it.optString("parent")==p.getString("id")}.map{display(it)}))}))
    }
    @Synchronized fun mutate(path:String,b:JSONObject):Any? {
        if(path !in listOf("/api/profiles","/api/profile-data","/api/favorite","/api/rating","/api/library-metadata","/api/library-catalog","/api/feedback","/api/track-comments"))return null
        val before=state.toString()
        try {
            val pid=effective(b.optString("profile","none"));val p=profile(pid)
            when(path){
                "/api/profiles"->{val action=b.getString("action");val key=b.optString("profile","none");val all=state.getJSONObject("profiles")
                    when(action){
                        "enabled"->state.put("enabled",b.getBoolean("enabled"))
                        "add"->{require(all.length()<50);val n=text(b.getString("name"),32);require(n.isNotBlank());all.put(id(),newProfile(n))}
                        "rename"->{require(key!="none");val n=text(b.getString("name"),32);require(n.isNotBlank());profile(key).put("name",n)}
                        "delete"->{require(key!="none");profile(key);all.remove(key)}
                        else->throw IllegalArgumentException("Unknown profile action")
                    }
                }
                "/api/profile-data"->{val values=b.getJSONObject("preferences");require(values.toString().length<=16000);values.keys().forEach{p.getJSONObject("preferences").put(it,values.get(it))}}
                "/api/favorite"->{val key=b.getString("track");track(key,pid);p.getJSONObject("favorites").put(key,b.getBoolean("favorite"))}
                "/api/rating"->{val key=b.getString("track");track(key,pid);if(b.isNull("rating"))p.getJSONObject("ratings").remove(key)else{val n=b.getInt("rating");require(n in 1..5);p.getJSONObject("ratings").put(key,n)}}
                "/api/library-metadata"->{check(b.getInt("revision")==state.getInt("revision")){"Library changed; reload and try again"};val key=b.getString("track");track(key,pid);val v=b.getJSONObject("values");val result=JSONObject(state.getJSONObject("metadata").optJSONObject(key)?.toString()?:"{}")
                    v.keys().forEach{k->require(k in listOf("title","description","creator","source_url","license","attribution","tags","categories"));if(k in listOf("tags","categories")){val ids=objects(state.getJSONArray(k)).map{it.getString("id")};val a=v.getJSONArray(k);require(a.length()<=100);for(i in 0 until a.length())require(a.getString(i) in ids);result.put(k,a)}else result.put(k,text(v.getString(k),if(k=="description")3000 else 1000))};state.getJSONObject("metadata").put(key,result)
                }
                "/api/library-catalog"->{check(b.getInt("revision")==state.getInt("revision")){"Library changed; reload and try again"};val kind=if(b.optString("action")=="add_tag")"tags"else b.getString("kind");require(kind in listOf("tags","categories"));val op=if(b.optString("action")=="add_tag")"add"else b.getString("operation");val rows=objects(state.getJSONArray(kind)).toMutableList();val key=b.optString("id")
                    when(op){"add"->{require(rows.size<150);val n=text(b.getString("name"),40);require(n.isNotBlank());rows.add(JSONObject().put("id",id()).put("name",n).put("picture","nature"))};"rename"->{val n=text(b.getString("name"),40);require(n.isNotBlank());val row=rows.first{it.getString("id")==key};row.put("name",n);if(kind=="categories"){val pic=b.optString("picture","nature");require(pic in listOf("weather","nature","water","noise","home","travel","music","tones"));row.put("picture",pic)}};"remove"->{require(b.getBoolean("confirm"));rows.removeAll{it.getString("id")==key};state.getJSONObject("metadata").keys().forEach{val m=state.getJSONObject("metadata").getJSONObject(it);val a=m.optJSONArray(kind)?:JSONArray();m.put(kind,JSONArray((0 until a.length()).map{a.getString(it)}.filter{it!=key}))}};else->throw IllegalArgumentException("Unknown label action")};state.put(kind,JSONArray(rows))
                }
                "/api/feedback","/api/track-comments"->{val rows=state.getJSONArray("posts");require(rows.length()<500);val body=text(b.getString("body"),2000);require(body.isNotBlank());val track=if(path.endsWith("track-comments"))b.getString("track")else "";if(track.isNotEmpty())track(track,pid)
                    val parent=if(b.isNull("parent"))null else b.getString("parent");if(parent!=null)require(objects(rows).any{it.getString("id")==parent&&it.optString("track")==track&&it.isNull("parent")})
                    val url=text(b.optString("url"),1000);if(url.isNotEmpty()){val uri=Uri.parse(url);require(uri.scheme in listOf("http","https")&&!uri.host.isNullOrBlank()&&uri.userInfo==null)}
                    rows.put(JSONObject().put("id",id()).put("profile",pid).put("track",track).put("parent",parent?:JSONObject.NULL).put("body",body).put("url",url).put("created_at",System.currentTimeMillis()/1000.0))
                }
            }
            state.put("revision",state.getInt("revision")+1);save()
            return when(path){"/api/profiles"->profiles();"/api/profile-data"->data(pid);"/api/library-catalog","/api/library-metadata"->catalog();"/api/feedback","/api/track-comments"->posts(if(path.endsWith("track-comments"))b.getString("track")else "");else->JSONObject().put("ok",true)}
        }catch(e:Exception){state=JSONObject(before);throw e}
    }
}
