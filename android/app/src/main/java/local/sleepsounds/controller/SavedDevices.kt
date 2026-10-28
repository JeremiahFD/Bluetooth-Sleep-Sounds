package local.sleepsounds.controller

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject

/** Private per-device connection/profile state. Switching devices never sends playback commands. */
class SavedDevices(context: Context, legacy: SharedPreferences) {
    private val prefs = context.getSharedPreferences("named_devices", Context.MODE_PRIVATE)
    data class Device(val key: String, var name: String, var lan: String, var alternate: String = "",
                      var mesh: String = "", var identity: String? = null, var profile: String? = null,
                      var discovery: Boolean = true)
    init {
        if (!prefs.contains("devices")) {
            save(listOf(
                Device("pi", "Remote host", legacy.getString("server", "").orEmpty(),
                    legacy.getString("lan_secondary", "").orEmpty(),legacy.getString("mesh", "").orEmpty(),
                    legacy.getString("host_id", null),legacy.getString("last_profile", null),legacy.getBoolean("discovery", true)),
                Device("onn", "This device", "http://127.0.0.1:8080")
            ))
        }
    }
    fun all(): List<Device> = try {
        val rows = JSONArray(prefs.getString("devices", "[]"))
        (0 until rows.length()).map { i -> rows.getJSONObject(i).let { j ->
            Device(j.getString("key"), j.getString("name"), j.getString("lan"), j.optString("alternate"),
                j.optString("mesh"), j.optString("identity").ifEmpty { null },
                j.optString("profile").ifEmpty { null }, j.optBoolean("discovery", true))
        } }
    } catch (_: Exception) { emptyList() }
    fun get(key: String) = all().firstOrNull { it.key == key }
    fun selected() = prefs.getString("selected", "pi") ?: "pi"
    fun select(key: String) { require(get(key) != null); prefs.edit().putString("selected", key).apply() }
    fun update(device: Device) { save(all().map { if (it.key == device.key) device else it }) }
    private fun save(devices: List<Device>) {
        val array = JSONArray()
        devices.forEach { d -> array.put(JSONObject().put("key", d.key).put("name", d.name)
            .put("lan", d.lan).put("alternate", d.alternate).put("mesh", d.mesh)
            .put("identity", d.identity ?: "").put("profile", d.profile ?: "").put("discovery", d.discovery)) }
        prefs.edit().putString("devices", array.toString()).apply()
    }
}
