package local.sleepsounds.controller

/** Monotonic, shared across discovery, address retries and page loading. */
class ConnectionBudget(started:Long, duration:Long=20_000) {
    val deadline=started+duration
    fun remaining(now:Long)=maxOf(0L,deadline-now)
    fun expired(now:Long)=remaining(now)==0L
    fun timeout(now:Long,limit:Int=1500)=minOf(remaining(now),limit.toLong()).toInt().coerceAtLeast(1)
}

object HostSelection {
    /** A configured default wins even when offline; callers must never replace it. */
    fun automatic(preferred:String?,reachable:List<Pair<String,String>>):String? =
        preferred ?: reachable.distinctBy{it.second}.singleOrNull()?.first
}
