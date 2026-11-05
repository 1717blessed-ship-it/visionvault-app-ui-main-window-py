# Integración ARCA: base implementada

Doccione incorpora una base local para perfiles fiscales, datos tributarios de
clientes y comprobantes inmutables vinculados a pedidos. Aún no realiza emisión
real: esa operación se habilitará solo tras homologación y configuración segura.

## Datos necesarios antes de producción

- condición frente al IVA y razón social del emisor;
- CUIT y punto de venta destinado a Web Services;
- certificado digital de producción y su clave, fuera del repositorio;
- autorización del servicio de factura electrónica en ARCA;
- definición de comprobantes a emitir (A, B o C).

## Flujo previsto

1. Configurar perfil fiscal en homologación.
2. Crear un borrador desde el pedido, que captura un *snapshot* del receptor y sus ítems.
3. Autorizarlo con ARCA y guardar número, CAE, vencimiento y PDF.
4. Enviar el PDF por WhatsApp y conservar el historial para auditoría.

No se deben editar ni borrar comprobantes autorizados. Correcciones posteriores
deben realizarse con el comprobante fiscal correspondiente (por ejemplo, nota de crédito).
