import 'dart:convert';

/// Job model representing a work order or task
class Job {
  final String id;
  final String? orderId;
  final String? jobNumber;
  final String? title;
  final String? material;
  final String? size;
  final int? quantity;
  final String? status;
  final String? notes;
  final int? sortOrder;
  final String? priority;
  final String? clientId;
  final String? assignedTo;
  final String? dueDate;
  final String? createdAt;
  final String? updatedAt;
  final Map<String, dynamic>? metadata;

  Job({
    required this.id,
    this.orderId,
    this.jobNumber,
    this.title,
    this.material,
    this.size,
    this.quantity,
    this.status,
    this.notes,
    this.sortOrder,
    this.priority,
    this.clientId,
    this.assignedTo,
    this.dueDate,
    this.createdAt,
    this.updatedAt,
    this.metadata,
  });

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'order_id': orderId,
      'job_number': jobNumber,
      'title': title,
      'material': material,
      'size': size,
      'quantity': quantity,
      'status': status,
      'notes': notes,
      'sort_order': sortOrder,
      'priority': priority,
      'client_id': clientId,
      'assigned_to': assignedTo,
      'due_date': dueDate,
      'created_at': createdAt,
      'updated_at': updatedAt,
      'metadata': metadata != null ? jsonEncode(metadata) : null,
    };
  }

  factory Job.fromMap(Map<String, dynamic> map) {
    return Job(
      id: map['id'] as String,
      orderId: map['order_id'] as String?,
      jobNumber: map['job_number'] as String?,
      title: map['title'] as String?,
      material: map['material'] as String?,
      size: map['size'] as String?,
      quantity: map['quantity'] as int?,
      status: map['status'] as String?,
      notes: map['notes'] as String?,
      sortOrder: map['sort_order'] as int?,
      priority: map['priority'] as String?,
      clientId: map['client_id'] as String?,
      assignedTo: map['assigned_to'] as String?,
      dueDate: map['due_date'] as String?,
      createdAt: map['created_at'] as String?,
      updatedAt: map['updated_at'] as String?,
      metadata: map['metadata'] != null 
          ? jsonDecode(map['metadata'] as String) as Map<String, dynamic>
          : null,
    );
  }

  Job copyWith({
    String? id,
    String? orderId,
    String? jobNumber,
    String? title,
    String? material,
    String? size,
    int? quantity,
    String? status,
    String? notes,
    int? sortOrder,
    String? priority,
    String? clientId,
    String? assignedTo,
    String? dueDate,
    String? createdAt,
    String? updatedAt,
    Map<String, dynamic>? metadata,
  }) {
    return Job(
      id: id ?? this.id,
      orderId: orderId ?? this.orderId,
      jobNumber: jobNumber ?? this.jobNumber,
      title: title ?? this.title,
      material: material ?? this.material,
      size: size ?? this.size,
      quantity: quantity ?? this.quantity,
      status: status ?? this.status,
      notes: notes ?? this.notes,
      sortOrder: sortOrder ?? this.sortOrder,
      priority: priority ?? this.priority,
      clientId: clientId ?? this.clientId,
      assignedTo: assignedTo ?? this.assignedTo,
      dueDate: dueDate ?? this.dueDate,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      metadata: metadata ?? this.metadata,
    );
  }
}
