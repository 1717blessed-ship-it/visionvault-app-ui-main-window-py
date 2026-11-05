import ARKit
import Flutter
import SceneKit
import UIKit

final class ArMockupViewFactory: NSObject, FlutterPlatformViewFactory {
  private let messenger: FlutterBinaryMessenger

  init(messenger: FlutterBinaryMessenger) {
    self.messenger = messenger
    super.init()
  }

  func create(
    withFrame frame: CGRect,
    viewIdentifier viewId: Int64,
    arguments args: Any?
  ) -> FlutterPlatformView {
    ArMockupPlatformView(
      frame: frame,
      viewId: viewId,
      arguments: args as? [String: Any] ?? [:],
      messenger: messenger
    )
  }

  func createArgsCodec() -> FlutterMessageCodec & NSObjectProtocol {
    FlutterStandardMessageCodec.sharedInstance()
  }
}

final class ArMockupPlatformView: NSObject, FlutterPlatformView {
  private let container: UIView
  private let sceneView: ARSCNView
  private let statusLabel: UILabel
  private let channel: FlutterMethodChannel
  private var overlayImage: UIImage?
  private var placedNode: SCNNode?
  private var placedTransform: simd_float4x4?
  private var sizeCm: Double = 10
  private var aspectRatio: Double = 1
  private var curved = false
  private let supported = ARWorldTrackingConfiguration.isSupported

  init(
    frame: CGRect,
    viewId: Int64,
    arguments: [String: Any],
    messenger: FlutterBinaryMessenger
  ) {
    container = UIView(frame: frame)
    sceneView = ARSCNView(frame: frame)
    statusLabel = UILabel(frame: .zero)
    channel = FlutterMethodChannel(
      name: "com.doccione.mobile/ar_mockup/\(viewId)",
      binaryMessenger: messenger
    )
    super.init()

    sceneView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
    sceneView.scene = SCNScene()
    sceneView.automaticallyUpdatesLighting = true
    container.addSubview(sceneView)

    statusLabel.translatesAutoresizingMaskIntoConstraints = false
    statusLabel.numberOfLines = 2
    statusLabel.textColor = .white
    statusLabel.backgroundColor = UIColor.black.withAlphaComponent(0.58)
    statusLabel.textAlignment = .center
    statusLabel.text = supported
      ? "Move el telefono para detectar una superficie"
      : "Este iPhone no es compatible con ARKit"
    container.addSubview(statusLabel)
    NSLayoutConstraint.activate([
      statusLabel.leadingAnchor.constraint(equalTo: container.leadingAnchor),
      statusLabel.trailingAnchor.constraint(equalTo: container.trailingAnchor),
      statusLabel.topAnchor.constraint(equalTo: container.topAnchor),
      statusLabel.heightAnchor.constraint(greaterThanOrEqualToConstant: 44),
    ])

    updateConfiguration(arguments)
    sceneView.addGestureRecognizer(UITapGestureRecognizer(target: self, action: #selector(placeDesign(_:))))
    channel.setMethodCallHandler { [weak self] call, result in
      self?.handle(call, result: result)
    }

    if supported {
      let configuration = ARWorldTrackingConfiguration()
      configuration.planeDetection = [.horizontal, .vertical]
      configuration.environmentTexturing = .automatic
      sceneView.session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
    }
  }

  deinit {
    channel.setMethodCallHandler(nil)
    sceneView.session.pause()
  }

  func view() -> UIView { container }

  private func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
    switch call.method {
    case "updateConfiguration":
      updateConfiguration(call.arguments as? [String: Any] ?? [:])
      channel.invokeMethod("status", arguments: [
        "supported": supported,
        "message": supported ? "Toca una superficie para colocar el diseno" : "ARKit no compatible",
      ])
      result(nil)
    case "reset":
      placedNode?.removeFromParentNode()
      placedNode = nil
      placedTransform = nil
      showStatus("Toca una superficie para colocar el diseno")
      result(nil)
    case "capture":
      capture(result: result)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  private func updateConfiguration(_ arguments: [String: Any]) {
    if let data = arguments["overlayBytes"] as? FlutterStandardTypedData {
      overlayImage = UIImage(data: data.data)
    }
    if let value = arguments["sizeCm"] as? NSNumber {
      sizeCm = min(max(value.doubleValue, 3), 29)
    }
    if let value = arguments["aspectRatio"] as? NSNumber {
      aspectRatio = min(max(value.doubleValue, 0.2), 5)
    }
    if let value = arguments["curved"] as? Bool { curved = value }
    rebuildPlacedNode()
  }

  @objc private func placeDesign(_ recognizer: UITapGestureRecognizer) {
    guard supported, overlayImage != nil else { return }
    let location = recognizer.location(in: sceneView)
    let hits = sceneView.hitTest(
      location,
      types: [.existingPlaneUsingExtent, .existingPlane, .estimatedHorizontalPlane, .estimatedVerticalPlane, .featurePoint]
    )
    guard let transform = hits.first?.worldTransform else {
      showStatus("No se encontro una superficie. Move el telefono e intenta otra vez")
      return
    }
    placedTransform = transform
    rebuildPlacedNode()
    showStatus("Diseno anclado. Toca otra superficie para moverlo")
  }

  private func rebuildPlacedNode() {
    guard let transform = placedTransform, let image = overlayImage else { return }
    placedNode?.removeFromParentNode()
    let node = SCNNode()
    node.simdTransform = transform
    let decal = SCNNode(geometry: makeGeometry(image: image))
    decal.position.y = 0.002
    node.addChildNode(decal)
    sceneView.scene.rootNode.addChildNode(node)
    placedNode = node
  }

  private func makeGeometry(image: UIImage) -> SCNGeometry {
    let width = Float(sizeCm / 100)
    let height = width / Float(aspectRatio)
    let segments = curved ? 32 : 1
    let radius = width * 0.72
    var vertices: [SCNVector3] = []
    var textureCoordinates: [CGPoint] = []
    var indices: [UInt16] = []

    for index in 0...segments {
      let progress = Float(index) / Float(segments)
      let x = -width / 2 + width * progress
      let depth = curved
        ? radius - sqrt(max(0, radius * radius - x * x))
        : 0
      vertices.append(SCNVector3(x, depth, -height / 2))
      vertices.append(SCNVector3(x, depth, height / 2))
      textureCoordinates.append(CGPoint(x: CGFloat(progress), y: 0))
      textureCoordinates.append(CGPoint(x: CGFloat(progress), y: 1))
      if index < segments {
        let start = UInt16(index * 2)
        indices.append(contentsOf: [start, start + 1, start + 2, start + 1, start + 3, start + 2])
      }
    }

    let sources = [
      SCNGeometrySource(vertices: vertices),
      SCNGeometrySource(textureCoordinates: textureCoordinates),
    ]
    let element = SCNGeometryElement(indices: indices, primitiveType: .triangles)
    let geometry = SCNGeometry(sources: sources, elements: [element])
    let material = SCNMaterial()
    material.diffuse.contents = image
    material.isDoubleSided = true
    material.lightingModel = .physicallyBased
    geometry.materials = [material]
    return geometry
  }

  private func capture(result: @escaping FlutterResult) {
    guard supported else {
      result(FlutterError(code: "ar_unavailable", message: "ARKit no esta disponible.", details: nil))
      return
    }
    let raw = sceneView.snapshot()
    let renderer = UIGraphicsImageRenderer(size: raw.size)
    let finalImage = renderer.image { context in
      raw.draw(in: CGRect(origin: .zero, size: raw.size))
      let fontSize = max(raw.size.width, 900) / 42
      let stripHeight = fontSize * 1.9
      UIColor.black.withAlphaComponent(0.75).setFill()
      context.cgContext.fill(CGRect(x: 0, y: raw.size.height - stripHeight, width: raw.size.width, height: stripHeight))
      "VISTA PREVIA AR - \(Int(sizeCm)) cm".draw(
        at: CGPoint(x: fontSize * 0.45, y: raw.size.height - stripHeight + fontSize * 0.35),
        withAttributes: [
          .foregroundColor: UIColor.white,
          .font: UIFont.boldSystemFont(ofSize: fontSize),
        ]
      )
    }
    guard let data = finalImage.pngData() else {
      result(FlutterError(code: "capture_failed", message: "No se pudo generar el PNG.", details: nil))
      return
    }
    let output = FileManager.default.temporaryDirectory
      .appendingPathComponent("ar_mockup_\(Int(Date().timeIntervalSince1970 * 1000)).png")
    do {
      try data.write(to: output, options: .atomic)
      result(output.path)
    } catch {
      result(FlutterError(code: "capture_failed", message: "No se pudo guardar el PNG.", details: error.localizedDescription))
    }
  }

  private func showStatus(_ message: String) {
    statusLabel.text = message
    channel.invokeMethod("status", arguments: ["supported": supported, "message": message])
  }
}
