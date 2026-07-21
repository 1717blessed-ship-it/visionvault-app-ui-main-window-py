import 'dart:convert';

/// Client model representing a customer or business contact
class Client {
  final String id;
  final String? name;
  final String? email;
  final String? phone;
  final String? company;
  final String? address;
  final String? createdAt;
  final String? updatedAt;
  final Map<String, dynamic>? metadata;

  Client({
    required this.id,
    this.name,
    this.email,
    this.phone,
    this.company,
    this.address,
    this.createdAt,
    this.updatedAt,
    this.metadata,
  });

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'name': name,
      'email': email,
      'phone': phone,
      'company': company,
      'address': address,
      'created_at': createdAt,
      'updated_at': updatedAt,
      'metadata': metadata != null ? jsonEncode(metadata) : null,
    };
  }

  factory Client.fromMap(Map<String, dynamic> map) {
    return Client(
      id: map['id'] as String,
      name: map['name'] as String?,
      email: map['email'] as String?,
      phone: map['phone'] as String?,
      company: map['company'] as String?,
      address: map['address'] as String?,
      createdAt: map['created_at'] as String?,
      updatedAt: map['updated_at'] as String?,
      metadata: map['metadata'] != null 
          ? jsonDecode(map['metadata'] as String) as Map<String, dynamic>
          : null,
    );
  }

  Client copyWith({
    String? id,
    String? name,
    String? email,
    String? phone,
    String? company,
    String? address,
    String? createdAt,
    String? updatedAt,
    Map<String, dynamic>? metadata,
  }) {
    return Client(
      id: id ?? this.id,
      name: name ?? this.name,
      email: email ?? this.email,
      phone: phone ?? this.phone,
      company: company ?? this.company,
      address: address ?? this.address,
      createdAt: createdAt ?? this.createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
      metadata: metadata ?? this.metadata,
    );
  }
}
