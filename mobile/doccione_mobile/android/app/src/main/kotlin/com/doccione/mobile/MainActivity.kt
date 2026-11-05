package com.doccione.mobile

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Matrix
import android.graphics.Path
import android.graphics.RectF
import androidx.core.content.FileProvider
import com.google.ar.core.ArCoreApk
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.android.FlutterActivity
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.FileOutputStream

class MainActivity: FlutterActivity() {
    private val arViews = mutableSetOf<ArMockupPlatformView>()

    fun registerArView(view: ArMockupPlatformView) { arViews.add(view) }
    fun unregisterArView(view: ArMockupPlatformView) { arViews.remove(view) }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        flutterEngine.platformViewsController.registry.registerViewFactory(
            "doccione/ar_mockup",
            ArMockupViewFactory(this, flutterEngine.dartExecutor.binaryMessenger),
        )
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "com.doccione.mobile/share")
            .setMethodCallHandler { call, result ->
                if (call.method == "isArAvailable") {
                    try {
                        val availability = ArCoreApk.getInstance().checkAvailability(this)
                        result.success(
                            availability == ArCoreApk.Availability.SUPPORTED_INSTALLED
                        )
                    } catch (_: Exception) {
                        result.success(false)
                    }
                    return@setMethodCallHandler
                }
                if (call.method == "composeMockup") {
                    try {
                        val photoPath = call.argument<String>("photoPath")
                        val overlayBytes = call.argument<ByteArray>("overlayBytes")
                        val base = photoPath?.let { BitmapFactory.decodeFile(it) }
                        val overlay = overlayBytes?.let { BitmapFactory.decodeByteArray(it, 0, it.size) }
                        if (base == null || overlay == null) {
                            result.error("compose_failed", "No se pudo leer la foto o el diseño.", null)
                            return@setMethodCallHandler
                        }
                        val left = (call.argument<Double>("left") ?: 0.0).toFloat() * base.width
                        val top = (call.argument<Double>("top") ?: 0.0).toFloat() * base.height
                        val width = (call.argument<Double>("width") ?: 1.0).toFloat() * base.width
                        val height = (call.argument<Double>("height") ?: 1.0).toFloat() * base.height
                        val rotation = (call.argument<Double>("rotationDegrees") ?: 0.0).toFloat()
                        val segments = (call.argument<Int>("segments") ?: 1).coerceIn(1, 48)
                        val mesh = call.argument<List<Double>>("mesh")
                        val sizeCm = call.argument<Int>("sizeCm") ?: 0
                        val composed = base.copy(Bitmap.Config.ARGB_8888, true)
                        val canvas = Canvas(composed)
                        if (mesh != null && mesh.size >= (segments + 1) * 4) {
                            val bitmapPaint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
                            for (segment in 0 until segments) {
                                val sourceLeft = overlay.width * segment.toFloat() / segments
                                val sourceRight = overlay.width * (segment + 1).toFloat() / segments
                                val source = floatArrayOf(
                                    sourceLeft, 0f,
                                    sourceRight, 0f,
                                    sourceRight, overlay.height.toFloat(),
                                    sourceLeft, overlay.height.toFloat(),
                                )
                                val current = segment * 4
                                val next = (segment + 1) * 4
                                val destination = floatArrayOf(
                                    mesh[current].toFloat() * base.width,
                                    mesh[current + 1].toFloat() * base.height,
                                    mesh[next].toFloat() * base.width,
                                    mesh[next + 1].toFloat() * base.height,
                                    mesh[next + 2].toFloat() * base.width,
                                    mesh[next + 3].toFloat() * base.height,
                                    mesh[current + 2].toFloat() * base.width,
                                    mesh[current + 3].toFloat() * base.height,
                                )
                                val matrix = Matrix().apply {
                                    setPolyToPoly(source, 0, destination, 0, 4)
                                }
                                val clip = Path().apply {
                                    moveTo(destination[0], destination[1])
                                    lineTo(destination[2], destination[3])
                                    lineTo(destination[4], destination[5])
                                    lineTo(destination[6], destination[7])
                                    close()
                                }
                                canvas.save()
                                canvas.clipPath(clip)
                                canvas.drawBitmap(overlay, matrix, bitmapPaint)
                                canvas.restore()
                            }
                        } else {
                            canvas.save()
                            canvas.rotate(rotation, left + width / 2, top + height / 2)
                            canvas.drawBitmap(overlay, null, RectF(left, top, left + width, top + height), null)
                            canvas.restore()
                        }
                        val label = "VISTA PREVIA • ${sizeCm} cm"
                        val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                            color = Color.WHITE
                            textSize = base.width.coerceAtLeast(900) / 42f
                            typeface = android.graphics.Typeface.DEFAULT_BOLD
                        }
                        val padding = labelPaint.textSize * .45f
                        val stripHeight = labelPaint.textSize + padding * 2
                        val stripPaint = Paint().apply { color = Color.argb(190, 0, 0, 0) }
                        canvas.drawRect(0f, base.height - stripHeight, base.width.toFloat(), base.height.toFloat(), stripPaint)
                        canvas.drawText(label, padding, base.height - padding, labelPaint)
                        val output = File(cacheDir, "mockup_${System.currentTimeMillis()}.png")
                        FileOutputStream(output).use {
                            composed.compress(Bitmap.CompressFormat.PNG, 100, it)
                        }
                        base.recycle()
                        overlay.recycle()
                        composed.recycle()
                        result.success(output.absolutePath)
                    } catch (error: Exception) {
                        result.error("compose_failed", "No se pudo crear el mockup.", error.message)
                    }
                    return@setMethodCallHandler
                }
                if (call.method != "shareImage") {
                    result.notImplemented()
                    return@setMethodCallHandler
                }
                val imagePath = call.argument<String>("path")
                val image = imagePath?.let(::File)
                if (image == null || !image.exists()) {
                    result.error("missing_image", "La foto no está disponible.", null)
                    return@setMethodCallHandler
                }
                val uri = FileProvider.getUriForFile(
                    this,
                    "$packageName.fileprovider",
                    image,
                )
                startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
                    type = "image/*"
                    putExtra(Intent.EXTRA_STREAM, uri)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }, "Enviar foto de referencia"))
                result.success(null)
            }
    }

    override fun onResume() {
        super.onResume()
        arViews.toList().forEach { it.onHostResume() }
    }

    override fun onPause() {
        arViews.toList().forEach { it.onHostPause() }
        super.onPause()
    }
}
