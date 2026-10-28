package local.sleepsounds.controller

import android.app.Activity
import android.app.AlertDialog
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Button
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/** Private, user-initiated self updater. No JS bridge, redirects or arbitrary APK URLs. */
class UpdateInstallerActivity : Activity() {
    private lateinit var message: TextView
    private var sessionId = -1
    private var started = false
    private val canceled=java.util.concurrent.atomic.AtomicBoolean(false)
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        val layout=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setPadding(40,70,40,40);setBackgroundColor(0xff091524.toInt()) }
        message=TextView(this).apply { text="Checking app updateÃ¢â‚¬Â¦";textSize=17f;setTextColor(0xffeef2fa.toInt()) }
        layout.addView(message)
        layout.addView(Button(this).apply { text="Close";setOnClickListener { canceled.set(true);finish() } })
        setContentView(layout)
        sessionId=state?.getInt("session",-1) ?: -1
        if(intent.action==STATUS)handleStatus(intent)
        else if(sessionId>=0)message.text="Waiting for Android installation result."
        else {
            val origin=intent.getStringExtra("origin") ?: return fail("Missing host address.")
            if(!packageManager.canRequestPackageInstalls()) {
                message.text="Allow Sleep Sounds to install its own updates, then return and tap Install / Update again."
                try { startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:$packageName"))) }
                catch (_: Exception) { fail("Open Android Settings and allow updates from Sleep Sounds.") }
            } else download(origin)
        }
    }
    override fun onSaveInstanceState(out: Bundle) { out.putInt("session",sessionId);super.onSaveInstanceState(out) }
    override fun onNewIntent(next: Intent) { super.onNewIntent(next);setIntent(next);if(next.action==STATUS)handleStatus(next) }
    private fun handleStatus(status: Intent) {
        when(status.getIntExtra(PackageInstaller.EXTRA_STATUS,PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION") val confirmation=status.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                if(confirmation!=null)try { startActivity(confirmation) } catch (_: Exception) { fail("Android confirmation could not be opened.") }
                else fail("Android did not provide installation confirmation.")
            }
            PackageInstaller.STATUS_SUCCESS -> { message.text="Update installed." }
            else -> fail("Update not installed. Android may have canceled or rejected it. Your data is preserved.")
        }
    }
    private fun fail(text:String) { if(!isFinishing)message.text=text }
    private fun get(url:String): HttpURLConnection {
        val c=URL(url).openConnection() as HttpURLConnection
        c.connectTimeout=8000;c.readTimeout=15000;c.instanceFollowRedirects=false
        if(c.responseCode!=200){c.disconnect();throw IllegalArgumentException("Host did not return a published release.")}
        return c
    }
    @Suppress("DEPRECATION")
    private fun signatures(info:PackageInfo):Set<String> {
        val all=if(Build.VERSION.SDK_INT>=28)info.signingInfo?.apkContentsSigners else info.signatures
        return all?.map { sha(it.toByteArray()) }?.toSet() ?: emptySet()
    }
    private fun sha(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02X".format(it.toInt() and 255)}
    @Suppress("DEPRECATION")
    private fun version(info:PackageInfo)=if(Build.VERSION.SDK_INT>=28)info.longVersionCode else info.versionCode.toLong()
    private fun download(origin:String) {
        if(started)return;started=true
        Thread({
            val apk=File.createTempFile("verified-app-update-", ".apk",cacheDir)
            try {
                val c=get("$origin/api/app-release")
                val raw=try { c.inputStream.use { input ->
                    val bytes=java.io.ByteArrayOutputStream();val buffer=ByteArray(1024)
                    while(bytes.size()<=8192){val n=input.read(buffer);if(n<0)break;bytes.write(buffer,0,n)}
                    bytes.toByteArray()
                } } finally { c.disconnect() }
                require(raw.size<=8192){"Release information is too large."}
                val release=JSONObject(String(raw,Charsets.UTF_8))
                require(release.optBoolean("available")){"No verified update is published."}
                val flags=if(Build.VERSION.SDK_INT>=28)PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
                val installed=packageManager.getPackageInfo(packageName,flags)
                require(release.getString("package")==packageName){"Wrong app package."}
                require(release.getLong("version_code")>version(installed)){"This app is already up to date."}
                val expectedHash=release.getString("sha256").uppercase()
                val expectedSigner=release.getString("signer_sha256").uppercase()
                require(expectedHash.matches(Regex("[0-9A-F]{64}")) && expectedSigner.matches(Regex("[0-9A-F]{64}"))){"Invalid release checksums."}
                val currentSigners=signatures(installed)
                require(currentSigners.size==1 && expectedSigner in currentSigners){"Release signer does not match this installed app."}
                runOnUiThread { message.text="Downloading verified app updateÃ¢â‚¬Â¦" }
                val download=get("$origin/install/SleepSounds.apk")
                val digest=MessageDigest.getInstance("SHA-256")
                var length=0L
                try {
                    require(download.contentLengthLong<=64L*1024*1024){"APK is too large."}
                    download.inputStream.use { input -> apk.outputStream().use { output ->
                        val buffer=ByteArray(65536)
                        while(true){require(!canceled.get()){ "Update canceled." };val count=input.read(buffer);if(count<0)break;length+=count
                            require(length<=64L*1024*1024){"APK is too large."};digest.update(buffer,0,count);output.write(buffer,0,count)}
                    } }
                } finally { download.disconnect() }
                require(digest.digest().joinToString(""){"%02X".format(it.toInt() and 255)}==expectedHash){"APK checksum failed. Nothing was installed."}
                val candidate=packageManager.getPackageArchiveInfo(apk.absolutePath,flags) ?: throw IllegalArgumentException("Unreadable APK.")
                require(candidate.packageName==packageName && version(candidate)==release.getLong("version_code")){"APK package or version mismatch."}
                require(signatures(candidate)==currentSigners){"APK signature does not match this app."}
                val installer=packageManager.packageInstaller
                val params=PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
                    setAppPackageName(packageName);setSize(length)
                    if(Build.VERSION.SDK_INT>=31)setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_REQUIRED)
                }
                sessionId=installer.createSession(params)
                installer.openSession(sessionId).use { session ->
                    session.openWrite("base.apk",0,length).use { out -> apk.inputStream().use { it.copyTo(out) };session.fsync(out) }
                    val callback=Intent(this,UpdateInstallerActivity::class.java).setAction(STATUS).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
                    val flagsPending=PendingIntent.FLAG_UPDATE_CURRENT or (if(Build.VERSION.SDK_INT>=31)PendingIntent.FLAG_MUTABLE else 0)
                    val pending=PendingIntent.getActivity(this,sessionId,callback,flagsPending)
                    require(!canceled.get()){ "Update canceled." }
                    session.commit(pending.intentSender)
                }
                runOnUiThread { message.text="Waiting for Android confirmationÃ¢â‚¬Â¦" }
            } catch(e:Exception) {
                if(sessionId>=0)try { packageManager.packageInstaller.abandonSession(sessionId) }catch(_:Exception){}
                sessionId=-1
                runOnUiThread { fail(e.message ?: "Update failed. Nothing was installed.") }
            } finally { apk.delete() }
        },"SleepSounds-app-update").start()
    }
    override fun onDestroy() { canceled.set(true);super.onDestroy() }
    companion object { private const val STATUS="local.sleepsounds.controller.INSTALL_STATUS" }
}
