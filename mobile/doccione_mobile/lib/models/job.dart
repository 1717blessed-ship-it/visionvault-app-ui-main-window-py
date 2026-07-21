import 'dart:convert';

/// Job model representing a work order or task
class Job {
  final String id;
  final String? jobNumber;
  final String? title;
  final String? status;
  final String? priority;
  final String? clientId;
  final String? assignedTo;
  final String? dueDate;
  final String? createdAt;
  final String? updatedAt;
  final Map<String, dynamic>? metadata;

  Job({
    required this.id,
    this.jobNumber,
    this.title,
    this.status,
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
      'job_number': jobNumber,
      'title': title,
      'status': status,
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
      jobNumber: map['job_number'] as String?,
      title: map['title'] as String?,
      status: map['status'] as String?,
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
    String? jobNumber,
    String? title,
    String? status,
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
      jobNumber: jobNumber ?? this.jobNumber,
      title: title ?? this.title,
      status: status ?? this.status,
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
