package com.doccione.mobile

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.opengl.GLES11Ext
import android.opengl.GLES20
import android.opengl.GLSurfaceView
import android.opengl.Matrix
import android.os.Handler
import android.os.Looper
import android.view.MotionEvent
import android.view.PixelCopy
import android.view.Surface
import android.view.View
import android.widget.FrameLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import com.google.ar.core.Anchor
import com.google.ar.core.ArCoreApk
import com.google.ar.core.Config
import com.google.ar.core.Coordinates2d
import com.google.ar.core.DepthPoint
import com.google.ar.core.Frame
import com.google.ar.core.Plane
import com.google.ar.core.Point
import com.google.ar.core.Pose
import com.google.ar.core.Session
import com.google.ar.core.TrackingState
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.StandardMessageCodec
import io.flutter.plugin.platform.PlatformView
import io.flutter.plugin.platform.PlatformViewFactory
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.nio.ShortBuffer
import java.util.concurrent.ConcurrentLinkedQueue
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10

class ArMockupViewFactory(
    private val activity: MainActivity,
    private val messenger: BinaryMessenger,
) : PlatformViewFactory(StandardMessageCodec.INSTANCE) {
    override fun create(context: Context, viewId: Int, args: Any?): PlatformView {
        val view = ArMockupPlatformView(activity, messenger, viewId, args as? Map<*, *> ?: emptyMap<Any, Any>())
        activity.registerArView(view)
        return view
    }
}

class ArMockupPlatformView(
    private val activity: MainActivity,
    messenger: BinaryMessenger,
    viewId: Int,
    arguments: Map<*, *>,
) : PlatformView, MethodChannel.MethodCallHandler {
    private val root = FrameLayout(activity)
    private val surface = GLSurfaceView(activity)
    private val status = TextView(activity)
    private val renderer = ArMockupRenderer(activity, ::showStatus)
    private val channel = MethodChannel(messenger, "com.doccione.mobile/ar_mockup/$viewId")
    private var session: Session? = null
    private var resumed = false
    private var installRequested = false

    init {
        surface.setEGLContextClientVersion(2)
        surface.preserveEGLContextOnPause = true
        surface.setRenderer(renderer)
        surface.renderMode = GLSurfaceView.RENDERMODE_CONTINUOUSLY
        surface.setOnTouchListener { _, event ->
            if (event.action == MotionEvent.ACTION_UP) {
                renderer.queueTap(event.x, event.y)
                true
            } else {
                true
            }
        }
        root.addView(surface, FrameLayout.LayoutParams(-1, -1))
        status.setTextColor(Color.WHITE)
        status.setBackgroundColor(Color.argb(150, 0, 0, 0))
        status.setPadding(24, 14, 24, 14)
        status.text = "Mové el teléfono para detectar una superficie"
        root.addView(status, FrameLayout.LayoutParams(-1, -2))
        renderer.updateConfiguration(arguments)
        channel.setMethodCallHandler(this)
        onHostResume()
    }

    override fun getView(): View = root

    override fun dispose() {
        channel.setMethodCallHandler(null)
        onHostPause()
        renderer.dispose()
        activity.unregisterArView(this)
    }

    fun onHostResume() {
        if (resumed) return
        if (ContextCompat.checkSelfPermission(activity, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            showStatus("La cámara necesita permiso para usar AR")
            return
        }
        val availability = ArCoreApk.getInstance().checkAvailability(activity)
        if (availability.isUnsupported) {
            showStatus("Este teléfono no es compatible con ARCore")
            channel.invokeMethod("status", mapOf("supported" to false, "message" to "ARCore no compatible"))
            return
        }
        try {
            val installStatus = ArCoreApk.getInstance().requestInstall(activity, !installRequested)
            if (installStatus == ArCoreApk.InstallStatus.INSTALL_REQUESTED) {
                installRequested = true
                showStatus("ARCore necesita instalarse antes del primer uso")
                return
            }
            if (session == null) {
                session = Session(activity).also { arSession ->
                    val config = Config(arSession).apply {
                        planeFindingMode = Config.PlaneFindingMode.HORIZONTAL_AND_VERTICAL
                        updateMode = Config.UpdateMode.LATEST_CAMERA_IMAGE
                        lightEstimationMode = Config.LightEstimationMode.ENVIRONMENTAL_HDR
                        if (arSession.isDepthModeSupported(Config.DepthMode.AUTOMATIC)) {
                            depthMode = Config.DepthMode.AUTOMATIC
                        }
                    }
                    arSession.configure(config)
                    renderer.session = arSession
                }
            }
            session?.resume()
            surface.onResume()
            resumed = true
            channel.invokeMethod("status", mapOf("supported" to true, "message" to "Buscando superficies"))
        } catch (error: Exception) {
            showStatus("ARCore no está instalado o actualizado")
            channel.invokeMethod("status", mapOf("supported" to false, "message" to error.javaClass.simpleName))
        }
    }

    fun onHostPause() {
        if (!resumed) return
        surface.onPause()
        session?.pause()
        resumed = false
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "updateConfiguration" -> {
                renderer.updateConfiguration(call.arguments as? Map<*, *> ?: emptyMap<Any, Any>())
                result.success(null)
            }
            "reset" -> {
                renderer.resetAnchor()
                showStatus("Tocá una superficie para colocar el diseño")
                result.success(null)
            }
            "capture" -> capture(result)
            else -> result.notImplemented()
        }
    }

    private fun capture(result: MethodChannel.Result) {
        if (surface.width < 1 || surface.height < 1) {
            result.error("capture_failed", "La vista AR todavía no está lista.", null)
            return
        }
        val bitmap = Bitmap.createBitmap(surface.width, surface.height, Bitmap.Config.ARGB_8888)
        PixelCopy.request(surface, bitmap, { copyResult ->
            if (copyResult != PixelCopy.SUCCESS) {
                bitmap.recycle()
                result.error("capture_failed", "No se pudo capturar la vista AR.", copyResult)
                return@request
            }
            val canvas = Canvas(bitmap)
            val fontSize = bitmap.width.coerceAtLeast(900) / 42f
            val padding = fontSize * .45f
            val stripHeight = fontSize * 1.9f
            canvas.drawRect(0f, bitmap.height - stripHeight, bitmap.width.toFloat(), bitmap.height.toFloat(), Paint().apply {
                color = Color.argb(190, 0, 0, 0)
            })
            canvas.drawText("VISTA PREVIA AR • ${renderer.sizeCm.toInt()} cm", padding, bitmap.height - padding, Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = Color.WHITE
                textSize = fontSize
                typeface = android.graphics.Typeface.DEFAULT_BOLD
            })
            val output = File(activity.cacheDir, "ar_mockup_${System.currentTimeMillis()}.png")
            FileOutputStream(output).use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
            bitmap.recycle()
            result.success(output.absolutePath)
        }, Handler(Looper.getMainLooper()))
    }

    private fun showStatus(message: String) {
        activity.runOnUiThread { status.text = message }
    }
}

private class ArMockupRenderer(
    private val activity: Activity,
    private val status: (String) -> Unit,
) : GLSurfaceView.Renderer {
    @Volatile var session: Session? = null
    @Volatile var sizeCm: Double = 10.0
        private set
    private var aspectRatio = 1.0
    private var curved = false
    private var overlayBytes: ByteArray? = null
    private var anchor: Anchor? = null
    private var frame: Frame? = null
    private val taps = ConcurrentLinkedQueue<Pair<Float, Float>>()
    private var viewportWidth = 1
    private var viewportHeight = 1
    private var cameraTexture = 0
    private var overlayTexture = 0
    private var backgroundProgram = 0
    private var objectProgram = 0
    private var textureAttached = false
    private var planeReported = false
    private var objectVertices: FloatBuffer? = null
    private var objectIndices: ShortBuffer? = null
    private var objectIndexCount = 0

    fun queueTap(x: Float, y: Float) { taps.add(x to y) }

    fun updateConfiguration(values: Map<*, *>) {
        (values["sizeCm"] as? Number)?.let { sizeCm = it.toDouble().coerceIn(3.0, 29.0) }
        (values["aspectRatio"] as? Number)?.let { aspectRatio = it.toDouble().coerceIn(.2, 5.0) }
        (values["curved"] as? Boolean)?.let { curved = it }
        (values["overlayBytes"] as? ByteArray)?.let {
            overlayBytes = it
            overlayTexture = 0
        }
        buildObjectMesh()
    }

    fun resetAnchor() {
        anchor?.detach()
        anchor = null
    }

    fun dispose() {
        resetAnchor()
        session?.close()
        session = null
    }

    override fun onSurfaceCreated(gl: GL10?, config: EGLConfig?) {
        GLES20.glClearColor(0f, 0f, 0f, 1f)
        cameraTexture = createExternalTexture()
        backgroundProgram = createProgram(BACKGROUND_VERTEX, BACKGROUND_FRAGMENT)
        objectProgram = createProgram(OBJECT_VERTEX, OBJECT_FRAGMENT)
        createOverlayTexture()
        buildObjectMesh()
    }

    override fun onSurfaceChanged(gl: GL10?, width: Int, height: Int) {
        viewportWidth = width.coerceAtLeast(1)
        viewportHeight = height.coerceAtLeast(1)
        GLES20.glViewport(0, 0, viewportWidth, viewportHeight)
        textureAttached = false
    }

    override fun onDrawFrame(gl: GL10?) {
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT or GLES20.GL_DEPTH_BUFFER_BIT)
        val activeSession = session ?: return
        try {
            if (!textureAttached) {
                activeSession.setCameraTextureName(cameraTexture)
                activeSession.setDisplayGeometry(displayRotation(), viewportWidth, viewportHeight)
                textureAttached = true
            }
            val currentFrame = activeSession.update()
            frame = currentFrame
            drawCamera(currentFrame)
            consumeTap(currentFrame)
            if (!planeReported && activeSession.getAllTrackables(Plane::class.java).any {
                    it.trackingState == TrackingState.TRACKING && it.subsumedBy == null
                }) {
                planeReported = true
                status("Superficie detectada. Tocala para colocar el diseño")
            }
            drawObject(currentFrame)
        } catch (_: Exception) {
            // ARCore can briefly lose the camera while the app changes lifecycle.
        }
    }

    private fun consumeTap(currentFrame: Frame) {
        val tap = taps.poll() ?: return
        val hit = currentFrame.hitTest(tap.first, tap.second).firstOrNull { result ->
            val trackable = result.trackable
            when (trackable) {
                is Plane -> trackable.trackingState == TrackingState.TRACKING &&
                    trackable.isPoseInPolygon(result.hitPose)
                is DepthPoint -> trackable.trackingState == TrackingState.TRACKING
                is Point -> trackable.trackingState == TrackingState.TRACKING &&
                    trackable.orientationMode == Point.OrientationMode.ESTIMATED_SURFACE_NORMAL
                else -> false
            }
        } ?: run {
            status("No se detectó una superficie en ese punto")
            return
        }
        anchor?.detach()
        anchor = hit.createAnchor()
        status("Diseño anclado · ${sizeCm.toInt()} cm")
    }

    private fun drawCamera(currentFrame: Frame) {
        if (currentFrame.timestamp == 0L) return
        val vertices = floatArrayOf(-1f, -1f, 1f, -1f, -1f, 1f, 1f, 1f)
        val inputVertices = floatBuffer(vertices)
        val textureBuffer = ByteBuffer.allocateDirect(8 * 4)
            .order(ByteOrder.nativeOrder()).asFloatBuffer()
        currentFrame.transformCoordinates2d(
            Coordinates2d.OPENGL_NORMALIZED_DEVICE_COORDINATES,
            inputVertices,
            Coordinates2d.TEXTURE_NORMALIZED,
            textureBuffer,
        )
        val vertexBuffer = floatBuffer(vertices)
        textureBuffer.position(0)
        GLES20.glDisable(GLES20.GL_DEPTH_TEST)
        GLES20.glUseProgram(backgroundProgram)
        val position = GLES20.glGetAttribLocation(backgroundProgram, "aPosition")
        val texCoord = GLES20.glGetAttribLocation(backgroundProgram, "aTexCoord")
        GLES20.glEnableVertexAttribArray(position)
        GLES20.glEnableVertexAttribArray(texCoord)
        GLES20.glVertexAttribPointer(position, 2, GLES20.GL_FLOAT, false, 0, vertexBuffer)
        GLES20.glVertexAttribPointer(texCoord, 2, GLES20.GL_FLOAT, false, 0, textureBuffer)
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, cameraTexture)
        GLES20.glUniform1i(GLES20.glGetUniformLocation(backgroundProgram, "uTexture"), 0)
        GLES20.glDrawArrays(GLES20.GL_TRIANGLE_STRIP, 0, 4)
        GLES20.glDisableVertexAttribArray(position)
        GLES20.glDisableVertexAttribArray(texCoord)
    }

    private fun drawObject(currentFrame: Frame) {
        val placedAnchor = anchor ?: return
        if (placedAnchor.trackingState != TrackingState.TRACKING) return
        if (overlayTexture == 0) createOverlayTexture()
        if (overlayTexture == 0) return
        val vertices = objectVertices ?: return
        val indices = objectIndices ?: return
        val projection = FloatArray(16)
        val view = FloatArray(16)
        val model = FloatArray(16)
        val viewModel = FloatArray(16)
        val mvp = FloatArray(16)
        currentFrame.camera.getProjectionMatrix(projection, 0, .05f, 50f)
        currentFrame.camera.getViewMatrix(view, 0)
        placedAnchor.pose.toMatrix(model, 0)
        Matrix.multiplyMM(viewModel, 0, view, 0, model, 0)
        Matrix.multiplyMM(mvp, 0, projection, 0, viewModel, 0)

        GLES20.glEnable(GLES20.GL_DEPTH_TEST)
        GLES20.glEnable(GLES20.GL_BLEND)
        GLES20.glBlendFunc(GLES20.GL_SRC_ALPHA, GLES20.GL_ONE_MINUS_SRC_ALPHA)
        GLES20.glUseProgram(objectProgram)
        GLES20.glUniformMatrix4fv(GLES20.glGetUniformLocation(objectProgram, "uMvp"), 1, false, mvp, 0)
        GLES20.glActiveTexture(GLES20.GL_TEXTURE0)
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, overlayTexture)
        GLES20.glUniform1i(GLES20.glGetUniformLocation(objectProgram, "uTexture"), 0)
        val stride = 5 * 4
        val position = GLES20.glGetAttribLocation(objectProgram, "aPosition")
        val texCoord = GLES20.glGetAttribLocation(objectProgram, "aTexCoord")
        vertices.position(0)
        GLES20.glEnableVertexAttribArray(position)
        GLES20.glVertexAttribPointer(position, 3, GLES20.GL_FLOAT, false, stride, vertices)
        vertices.position(3)
        GLES20.glEnableVertexAttribArray(texCoord)
        GLES20.glVertexAttribPointer(texCoord, 2, GLES20.GL_FLOAT, false, stride, vertices)
        indices.position(0)
        GLES20.glDrawElements(GLES20.GL_TRIANGLES, objectIndexCount, GLES20.GL_UNSIGNED_SHORT, indices)
        GLES20.glDisableVertexAttribArray(position)
        GLES20.glDisableVertexAttribArray(texCoord)
    }

    private fun buildObjectMesh() {
        val segments = if (curved) 32 else 1
        val width = (sizeCm / 100.0).toFloat()
        val height = (width / aspectRatio).toFloat()
        val radius = width * .72f
        val vertices = ArrayList<Float>((segments + 1) * 10)
        for (index in 0..segments) {
            val progress = index.toFloat() / segments
            val x = -width / 2 + width * progress
            val curve = if (curved) {
                radius - kotlin.math.sqrt((radius * radius - x * x).coerceAtLeast(0f))
            } else 0f
            vertices.addAll(listOf(x, curve + .002f, -height / 2, progress, 0f))
            vertices.addAll(listOf(x, curve + .002f, height / 2, progress, 1f))
        }
        val indices = ArrayList<Short>(segments * 6)
        for (index in 0 until segments) {
            val topLeft = (index * 2).toShort()
            val bottomLeft = (index * 2 + 1).toShort()
            val topRight = (index * 2 + 2).toShort()
            val bottomRight = (index * 2 + 3).toShort()
            indices.addAll(listOf(topLeft, bottomLeft, topRight, topRight, bottomLeft, bottomRight))
        }
        objectVertices = floatBuffer(vertices.toFloatArray())
        objectIndices = ByteBuffer.allocateDirect(indices.size * 2)
            .order(ByteOrder.nativeOrder()).asShortBuffer().apply {
                put(indices.toShortArray())
                position(0)
            }
        objectIndexCount = indices.size
    }

    private fun createOverlayTexture() {
        val bytes = overlayBytes ?: return
        val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return
        val textures = IntArray(1)
        GLES20.glGenTextures(1, textures, 0)
        overlayTexture = textures[0]
        GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, overlayTexture)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
        android.opengl.GLUtils.texImage2D(GLES20.GL_TEXTURE_2D, 0, bitmap, 0)
        bitmap.recycle()
    }

    private fun createExternalTexture(): Int {
        val textures = IntArray(1)
        GLES20.glGenTextures(1, textures, 0)
        GLES20.glBindTexture(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, textures[0])
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE)
        GLES20.glTexParameteri(GLES11Ext.GL_TEXTURE_EXTERNAL_OES, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE)
        return textures[0]
    }

    private fun displayRotation(): Int = if (android.os.Build.VERSION.SDK_INT >= 30) {
        activity.display?.rotation ?: Surface.ROTATION_0
    } else {
        @Suppress("DEPRECATION")
        activity.windowManager.defaultDisplay.rotation
    }

    private fun createProgram(vertex: String, fragment: String): Int {
        fun shader(type: Int, source: String): Int = GLES20.glCreateShader(type).also {
            GLES20.glShaderSource(it, source)
            GLES20.glCompileShader(it)
        }
        return GLES20.glCreateProgram().also {
            GLES20.glAttachShader(it, shader(GLES20.GL_VERTEX_SHADER, vertex))
            GLES20.glAttachShader(it, shader(GLES20.GL_FRAGMENT_SHADER, fragment))
            GLES20.glLinkProgram(it)
        }
    }

    private fun floatBuffer(values: FloatArray): FloatBuffer =
        ByteBuffer.allocateDirect(values.size * 4).order(ByteOrder.nativeOrder())
            .asFloatBuffer().apply { put(values); position(0) }

    companion object {
        private const val BACKGROUND_VERTEX = """
            attribute vec2 aPosition;
            attribute vec2 aTexCoord;
            varying vec2 vTexCoord;
            void main() { gl_Position = vec4(aPosition, 0.0, 1.0); vTexCoord = aTexCoord; }
        """
        private const val BACKGROUND_FRAGMENT = """
            #extension GL_OES_EGL_image_external : require
            precision mediump float;
            uniform samplerExternalOES uTexture;
            varying vec2 vTexCoord;
            void main() { gl_FragColor = texture2D(uTexture, vTexCoord); }
        """
        private const val OBJECT_VERTEX = """
            uniform mat4 uMvp;
            attribute vec3 aPosition;
            attribute vec2 aTexCoord;
            varying vec2 vTexCoord;
            void main() { gl_Position = uMvp * vec4(aPosition, 1.0); vTexCoord = aTexCoord; }
        """
        private const val OBJECT_FRAGMENT = """
            precision mediump float;
            uniform sampler2D uTexture;
            varying vec2 vTexCoord;
            void main() { gl_FragColor = texture2D(uTexture, vTexCoord); }
        """
    }
}
