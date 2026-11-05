import Flutter
import ARKit
import CoreImage
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    guard let registrar = engineBridge.pluginRegistry.registrar(
      forPlugin: "DoccioneMockupComposer"
    ) else { return }
    let channel = FlutterMethodChannel(
      name: "com.doccione.mobile/share",
      binaryMessenger: registrar.messenger()
    )
    registrar.register(
      ArMockupViewFactory(messenger: registrar.messenger()),
      withId: "doccione/ar_mockup"
    )
    channel.setMethodCallHandler { [weak self] call, result in
      guard let self else { return }
      switch call.method {
      case "isArAvailable":
        result(ARWorldTrackingConfiguration.isSupported)
      case "composeMockup":
        self.composeMockup(call: call, result: result)
      case "shareImage":
        self.shareImage(call: call, result: result)
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }

  private func composeMockup(call: FlutterMethodCall, result: @escaping FlutterResult) {
    guard
      let arguments = call.arguments as? [String: Any],
      let photoPath = arguments["photoPath"] as? String,
      let base = UIImage(contentsOfFile: photoPath),
      let typedData = arguments["overlayBytes"] as? FlutterStandardTypedData,
      let overlay = UIImage(data: typedData.data),
      let baseCI = CIImage(image: base),
      let overlayCI = CIImage(image: overlay)
    else {
      result(FlutterError(code: "compose_failed", message: "No se pudo leer la foto o el diseño.", details: nil))
      return
    }

    let segments = min(max(arguments["segments"] as? Int ?? 1, 1), 48)
    let mesh = (arguments["mesh"] as? [NSNumber]) ?? []
    let baseWidth = baseCI.extent.width
    let baseHeight = baseCI.extent.height
    var composed = baseCI
    if mesh.count >= (segments + 1) * 4 {
      for segment in 0..<segments {
        let sourceLeft = overlayCI.extent.width * CGFloat(segment) / CGFloat(segments)
        let sourceRight = overlayCI.extent.width * CGFloat(segment + 1) / CGFloat(segments)
        let slice = overlayCI.cropped(to: CGRect(
          x: sourceLeft,
          y: overlayCI.extent.minY,
          width: sourceRight - sourceLeft,
          height: overlayCI.extent.height
        ))
        let current = segment * 4
        let next = (segment + 1) * 4
        func point(_ offset: Int) -> CGPoint {
          CGPoint(
            x: CGFloat(truncating: mesh[offset]) * baseWidth,
            y: baseHeight - CGFloat(truncating: mesh[offset + 1]) * baseHeight
          )
        }
        guard let filter = CIFilter(name: "CIPerspectiveTransform") else { continue }
        filter.setValue(slice, forKey: kCIInputImageKey)
        filter.setValue(CIVector(cgPoint: point(current)), forKey: "inputTopLeft")
        filter.setValue(CIVector(cgPoint: point(next)), forKey: "inputTopRight")
        filter.setValue(CIVector(cgPoint: point(next + 2)), forKey: "inputBottomRight")
        filter.setValue(CIVector(cgPoint: point(current + 2)), forKey: "inputBottomLeft")
        if let warped = filter.outputImage {
          composed = warped.composited(over: composed)
        }
      }
    }

    let context = CIContext(options: nil)
    guard let cgImage = context.createCGImage(composed, from: baseCI.extent) else {
      result(FlutterError(code: "compose_failed", message: "No se pudo renderizar el mockup.", details: nil))
      return
    }
    let raw = UIImage(cgImage: cgImage, scale: base.scale, orientation: base.imageOrientation)
    let sizeCm = arguments["sizeCm"] as? Int ?? 0
    let renderer = UIGraphicsImageRenderer(size: raw.size)
    let finalImage = renderer.image { rendererContext in
      raw.draw(in: CGRect(origin: .zero, size: raw.size))
      let fontSize = max(raw.size.width, 900) / 42
      let stripHeight = fontSize * 1.9
      UIColor.black.withAlphaComponent(0.75).setFill()
      rendererContext.cgContext.fill(CGRect(x: 0, y: raw.size.height - stripHeight, width: raw.size.width, height: stripHeight))
      let label = "VISTA PREVIA • \(sizeCm) cm"
      label.draw(
        at: CGPoint(x: fontSize * 0.45, y: raw.size.height - stripHeight + fontSize * 0.35),
        withAttributes: [
          .foregroundColor: UIColor.white,
          .font: UIFont.boldSystemFont(ofSize: fontSize),
        ]
      )
    }
    guard let data = finalImage.pngData() else {
      result(FlutterError(code: "compose_failed", message: "No se pudo guardar el mockup.", details: nil))
      return
    }
    let output = FileManager.default.temporaryDirectory
      .appendingPathComponent("mockup_\(Int(Date().timeIntervalSince1970 * 1000)).png")
    do {
      try data.write(to: output, options: .atomic)
      result(output.path)
    } catch {
      result(FlutterError(code: "compose_failed", message: "No se pudo guardar el mockup.", details: error.localizedDescription))
    }
  }

  private func shareImage(call: FlutterMethodCall, result: @escaping FlutterResult) {
    guard
      let arguments = call.arguments as? [String: Any],
      let imagePath = arguments["path"] as? String,
      FileManager.default.fileExists(atPath: imagePath)
    else {
      result(FlutterError(code: "missing_image", message: "La foto no está disponible.", details: nil))
      return
    }
    let controller = UIActivityViewController(
      activityItems: [URL(fileURLWithPath: imagePath)],
      applicationActivities: nil
    )
    var presenter = window?.rootViewController
    while let presented = presenter?.presentedViewController { presenter = presented }
    presenter?.present(controller, animated: true)
    result(nil)
  }
}
