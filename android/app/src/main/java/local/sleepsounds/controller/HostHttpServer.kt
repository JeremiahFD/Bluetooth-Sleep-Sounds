package local.sleepsounds.controller

import android.content.Context
import android.net.Uri
import org.json.JSONObject
import java.io.*
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.SynchronousQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit

/** Small bounded LAN server; no shell, arbitrary paths, URL fetcher or permissive CORS. */
class HostHttpServer(private val context: Context, private val host: AndroidHostService) : Closeable {
    private var listener: ServerSocket? = null
    @Volatile private var closed = false
    // Browsers preconnect idle sockets. Never queue actual requests behind them.
    private val workers = ThreadPoolExecutor(0, 8, 30, TimeUnit.SECONDS, SynchronousQueue<Runnable>(),
        { task -> Thread(task, "SleepSounds-host-request") }, ThreadPoolExecutor.AbortPolicy())
    fun start() {
        listener = ServerSocket().apply { reuseAddress = true; bind(java.net.InetSocketAddress("0.0.0.0", 8080)) }
        Thread({
            while (!closed) try {
                val socket = listener!!.accept().apply { soTimeout = 3000 }
                try { workers.execute { socket.use { serve(it) } } } catch (_: Exception) { socket.close() }
            } catch (_: IOException) { if (!closed) host.note("HTTP accept failed") }
        }, "SleepSounds-host-listener").start()
    }
    private fun line(input: InputStream): String {
        val out = ByteArrayOutputStream()
        while (out.size() < 8192) {
            val b = input.read()
            if (b < 0) throw EOFException()
            if (b == 10) return out.toString("US-ASCII").removeSuffix("\r")
            out.write(b)
        }
        throw IllegalArgumentException("Header too long")
    }
    private fun localHost(authority: String): Boolean {
        if (!authority.matches(Regex("[0-9.]+:8080"))) return false
        val address = authority.substringBefore(':')
        if (address == "127.0.0.1") return true
        return NetworkInterface.getNetworkInterfaces().toList().flatMap { it.inetAddresses.toList() }
            .any { it.hostAddress == address }
    }
    private fun privatePeer(address: InetAddress): Boolean {
        val b = address.address
        return address.isLoopbackAddress || address.isSiteLocalAddress ||
            (b.size == 4 && (b[0].toInt() and 255) == 100 && (b[1].toInt() and 255) in 64..127)
    }
    private fun reply(socket: Socket, code: Int, mime: String, bytes: ByteArray, head: Boolean = false) {
        val reason = when(code) { 200 -> "OK"; 400 -> "Bad Request"; 403 -> "Forbidden"; 404 -> "Not Found";
            409 -> "Conflict"; 413 -> "Content Too Large"; 422 -> "Unprocessable Content"; else -> "Service Unavailable" }
        val headers = "HTTP/1.1 $code $reason\r\nContent-Type: $mime\r\nContent-Length: ${bytes.size}\r\n" +
            "Connection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n" +
            "Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'\r\n\r\n"
        socket.getOutputStream().apply { write(headers.toByteArray(Charsets.US_ASCII)); if (!head) write(bytes); flush() }
    }
    private fun serve(socket: Socket) {
        try {
            require(privatePeer(socket.inetAddress)) { "Private network required" }
            val input = BufferedInputStream(socket.getInputStream(), 65536)
            val parts = line(input).split(' ')
            require(parts.size == 3 && parts[0] in listOf("GET", "HEAD", "POST") && parts[2] in listOf("HTTP/1.1", "HTTP/1.0"))
            val method = parts[0]; val target = parts[1]
            require(target.startsWith('/') && !target.startsWith("//") && target.length <= 4096)
            val headers = mutableMapOf<String,String>(); var total = 0; var count = 0
            while (true) {
                val row = line(input); total += row.length
                require(total <= 16384 && ++count <= 40)
                if (row.isEmpty()) break
                require(':' in row)
                val key = row.substringBefore(':').lowercase()
                require(!headers.containsKey(key)) { "Duplicate header" }
                headers[key] = row.substringAfter(':').trim()
            }
            socket.soTimeout=15000 // Streaming uploads get a separate inactivity budget.
            dispatch(socket,input,method,target,headers)
        } catch (error: Exception) {
            try { reply(socket,if(error is IllegalStateException)409 else 400,"application/json",
                JSONObject().put("error",(error.message ?: "Request failed").take(180)).toString().toByteArray()) }
            catch (_: Exception) { }
        }
    }

    private fun dispatch(socket: Socket, input: InputStream, method: String, target: String, headers: Map<String,String>) {
        val authority = headers["host"].orEmpty()
        require(localHost(authority)) { "Invalid host" }
        require(!headers.containsKey("transfer-encoding")) { "Chunked requests unsupported" }
        val uri = Uri.parse(target); val path = uri.path.orEmpty()
        val length = headers["content-length"]?.toLongOrNull() ?: 0L
        require(length >= 0)
        if (method == "POST") {
            if (headers["origin"] != "http://$authority" || headers["x-sleep-token"] != host.token) {
                reply(socket,403,"application/json",JSONObject().put("error","Reload this host page before making changes.").toString().toByteArray()); return
            }
            if(path=="/api/artwork") {val result=host.importArtwork(uri.getQueryParameter("track").orEmpty(),input,length);reply(socket,200,"application/json",result.toString().toByteArray());return}
            if (path == "/api/upload") {
                require(length in 1..900_000_000L)
                val name = uri.getQueryParameter("name") ?: throw IllegalArgumentException("Name required")
                val result = host.importAudio(name, input, length)
                reply(socket,200,"application/json",result.toString().toByteArray());return
            }
            require(length <= 65536 && headers["content-type"].orEmpty().substringBefore(';') == "application/json")
            val raw = ByteArray(length.toInt()); var at = 0
            while (at < raw.size) { val n=input.read(raw,at,raw.size-at); if(n<0)throw EOFException();at+=n }
            val body = JSONObject(String(raw,Charsets.UTF_8).ifEmpty { "{}" })
            val result = host.onMain { host.mutate(path, body) }
            reply(socket,200,"application/json",result.toString().toByteArray());return
        }
        if(path=="/api/artwork") {val bytes=host.artwork(uri.getQueryParameter("track").orEmpty());if(bytes==null)reply(socket,404,"text/plain",byteArrayOf())else {val mime=android.graphics.BitmapFactory.Options().apply{inJustDecodeBounds=true}.let{android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.size,it);it.outMimeType};reply(socket,200,mime?:"application/octet-stream",bytes,method=="HEAD")};return}
        if (path.startsWith("/api/")) {
            val data = when(path) {
                "/api/identity" -> host.identity()
                "/api/status" -> host.onMain { host.status() }
                "/api/tracks" -> host.onMain { host.readApi(path,uri)!! }
                "/api/diagnostics-export" -> host.onMain { host.diagnostics() }
                else -> host.onMain {host.readApi(path,uri)} ?: run{reply(socket,404,"application/json","{\"error\":\"Not yet supported on Android.\"}".toByteArray());return}
            }
            reply(socket,200,"application/json",data.toString().toByteArray(),method=="HEAD");return
        }
        val relative=when {path in listOf("/","/ui/","/ui/index.html")->"index.html";path.startsWith("/ui/")->path.removePrefix("/ui/");else->""}
        if(relative.isBlank()||relative.split('/').any{it.isBlank()||it=="."||it==".."}||relative.contains('\\')){reply(socket,404,"text/plain","Not found".toByteArray());return}
        val mime=when(relative.substringAfterLast('.')){"html"->"text/html; charset=utf-8";"js"->"application/javascript";"css"->"text/css";"svg"->"image/svg+xml";"png"->"image/png";"webp"->"image/webp";"jpg","jpeg"->"image/jpeg";else->"application/octet-stream"}
        val bytes=try{context.assets.open("full-ui/"+relative).use{it.readBytes()}}catch(_:IOException){reply(socket,404,"text/plain","Not found".toByteArray());return}
        reply(socket,200,mime,bytes,method=="HEAD")
    }
    override fun close() { closed=true; try {listener?.close()}catch(_:Exception){};workers.shutdownNow() }
}
