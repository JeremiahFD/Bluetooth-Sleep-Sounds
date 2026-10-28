package local.sleepsounds.controller

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Handler
import android.os.Looper
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Bounded, on-demand LAN discovery. Advertisements are hints, never host authentication. */
class HostDiscovery(context: Context) {
    private val manager = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    data class Host(val name: String, val address: String)

    @Suppress("DEPRECATION")
    fun find(): List<Host> {
        check(Looper.myLooper() != Looper.getMainLooper())
        val found = linkedMapOf<String, NsdServiceInfo>()
        val hosts = linkedMapOf<String, Host>()
        val ended = CountDownLatch(1)
        val active = java.util.concurrent.atomic.AtomicBoolean(true)
        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(type: String) {}
            override fun onDiscoveryStopped(type: String) { ended.countDown() }
            override fun onStartDiscoveryFailed(type: String, code: Int) { ended.countDown() }
            override fun onStopDiscoveryFailed(type: String, code: Int) { ended.countDown() }
            override fun onServiceFound(service: NsdServiceInfo) {
                if (active.get() && service.serviceType.trimEnd('.') == "_sleep-sounds._tcp")
                    synchronized(found) { if(found.size < 16) found[service.serviceName] = service }
            }
            override fun onServiceLost(service: NsdServiceInfo) {
                synchronized(found) { found.remove(service.serviceName) }
            }
        }
        val main = Handler(Looper.getMainLooper())
        try {
            manager.discoverServices("_sleep-sounds._tcp.", NsdManager.PROTOCOL_DNS_SD, listener)
            main.postDelayed({ ended.countDown() }, 4000)
            ended.await(5, TimeUnit.SECONDS)
            // Serialize resolutions: older Android versions allow only one outstanding resolve.
            for (service in synchronized(found) { found.values.toList() }) {
                val resolved = CountDownLatch(1)
                manager.resolveService(service, object : NsdManager.ResolveListener {
                    override fun onResolveFailed(info: NsdServiceInfo, code: Int) { resolved.countDown() }
                    override fun onServiceResolved(info: NsdServiceInfo) {
                        val ip = info.host?.hostAddress.orEmpty()
                        if(active.get() && ip.matches(Regex("[0-9.]+")) && info.port in 1..65535) {
                            val address = "http://$ip:${info.port}"
                            synchronized(hosts) { hosts[address] = Host(info.serviceName, address) }
                        }
                        resolved.countDown()
                    }
                })
                if(!resolved.await(700, TimeUnit.MILLISECONDS)) break
            }
        } finally {
            active.set(false)
            try { manager.stopServiceDiscovery(listener) } catch(_: Exception) {}
        }
        return synchronized(hosts) { hosts.values.toList() }
    }
}
