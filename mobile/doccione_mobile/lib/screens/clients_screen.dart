import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../database/clients_repository.dart';
import '../database/database_helper.dart';
import '../models/client.dart';

/// Cartera local del vendedor. Las altas se conservan sin conexión y se
/// incorporan a la próxima sincronización cuando Studio las admita.
class ClientsScreen extends StatefulWidget {
  const ClientsScreen({super.key});

  @override
  State<ClientsScreen> createState() => _ClientsScreenState();
}

class _ClientsScreenState extends State<ClientsScreen> {
  final _search = TextEditingController();
  late final ClientsRepository _repository;
  List<Client> _clients = const [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _repository = ClientsRepository(DatabaseHelper());
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final query = _search.text.trim();
    final clients = query.isEmpty
        ? await _repository.getAllClients()
        : await _repository.searchClientsByName(query);
    if (!mounted) return;
    setState(() {
      _clients = clients;
      _loading = false;
    });
  }

  Future<void> _edit([Client? current]) async {
    final saved = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _ClientEditor(client: current, repository: _repository),
    );
    if (saved == true) await _load();
  }

  Future<void> _openWhatsapp(Client client) async {
    final number = (client.phone ?? '').replaceAll(RegExp(r'[^0-9]'), '');
    if (number.isEmpty) return;
    final opened = await launchUrl(Uri.parse('https://wa.me/$number'));
    if (!opened && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('No se pudo abrir WhatsApp.')),
      );
    }
  }

  Future<void> _delete(Client client) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Eliminar cliente'),
        content: Text(
            '¿Eliminar a ${client.name ?? 'este cliente'}? Esta acción no se puede deshacer.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Cancelar')),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: Theme.of(context).colorScheme.error),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Eliminar'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _repository.deleteClient(client.id);
    await _load();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${client.name ?? 'Cliente'} eliminado.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Clientes')),
        floatingActionButton: FloatingActionButton.extended(
          onPressed: () => _edit(),
          icon: const Icon(Icons.person_add_alt_1),
          label: const Text('Nuevo cliente'),
        ),
        body: Column(children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: TextField(
              controller: _search,
              onChanged: (_) => _load(),
              decoration: InputDecoration(
                labelText: 'Buscar cliente',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _search.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () {
                          _search.clear();
                          _load();
                        },
                      ),
              ),
            ),
          ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : _clients.isEmpty
                    ? const Center(child: Text('Todavía no hay clientes.'))
                    : ListView.separated(
                        padding: const EdgeInsets.fromLTRB(16, 0, 16, 96),
                        itemCount: _clients.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 8),
                        itemBuilder: (_, index) {
                          final client = _clients[index];
                          return Card(
                            child: ListTile(
                              leading: CircleAvatar(
                                child: Text((client.name ?? '?').trim().isEmpty
                                    ? '?'
                                    : client.name!.trim()[0].toUpperCase()),
                              ),
                              title: Text(client.name ?? 'Sin nombre'),
                              subtitle: Text([
                                if ((client.phone ?? '').isNotEmpty)
                                  client.phone!,
                                if ((client.company ?? '').isNotEmpty)
                                  client.company!,
                              ].join(' · ')),
                              onTap: () => _edit(client),
                              onLongPress: () => _delete(client),
                              trailing: (client.phone ?? '').isEmpty
                                  ? const Icon(Icons.edit_outlined)
                                  : IconButton(
                                      tooltip: 'Abrir WhatsApp',
                                      icon: const Icon(Icons.chat_outlined),
                                      onPressed: () => _openWhatsapp(client),
                                    ),
                            ),
                          );
                        },
                      ),
          ),
        ]),
      );
}

class _ClientEditor extends StatefulWidget {
  final Client? client;
  final ClientsRepository repository;
  const _ClientEditor({this.client, required this.repository});

  @override
  State<_ClientEditor> createState() => _ClientEditorState();
}

class _ClientEditorState extends State<_ClientEditor> {
  late final TextEditingController _name;
  late final TextEditingController _phone;
  late final TextEditingController _email;
  late final TextEditingController _company;
  late final TextEditingController _address;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    final client = widget.client;
    _name = TextEditingController(text: client?.name ?? '');
    _phone = TextEditingController(text: client?.phone ?? '');
    _email = TextEditingController(text: client?.email ?? '');
    _company = TextEditingController(text: client?.company ?? '');
    _address = TextEditingController(text: client?.address ?? '');
  }

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _email.dispose();
    _company.dispose();
    _address.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty) return;
    setState(() => _saving = true);
    final now = DateTime.now().toUtc().toIso8601String();
    await widget.repository.upsertClient(Client(
      id: widget.client?.id ??
          'local-client-${DateTime.now().microsecondsSinceEpoch}',
      name: _name.text.trim(),
      phone: _phone.text.trim(),
      email: _email.text.trim(),
      company: _company.text.trim(),
      address: _address.text.trim(),
      createdAt: widget.client?.createdAt ?? now,
      updatedAt: now,
      metadata: {'pending_sync': true},
    ).toMap());
    if (mounted) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.fromLTRB(
            20, 20, 20, 20 + MediaQuery.viewInsetsOf(context).bottom),
        child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(widget.client == null ? 'Nuevo cliente' : 'Editar cliente',
              style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 16),
          TextField(
              controller: _name,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Nombre *')),
          TextField(
              controller: _phone,
              keyboardType: TextInputType.phone,
              decoration:
                  const InputDecoration(labelText: 'WhatsApp / teléfono')),
          TextField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              decoration: const InputDecoration(labelText: 'Email')),
          TextField(
              controller: _company,
              decoration: const InputDecoration(labelText: 'Empresa')),
          TextField(
              controller: _address,
              maxLines: 2,
              decoration: const InputDecoration(labelText: 'Dirección')),
          const SizedBox(height: 20),
          SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _saving ? null : _save,
                child: Text(_saving ? 'Guardando...' : 'Guardar cliente'),
              )),
        ])),
      );
}
