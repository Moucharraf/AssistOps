class AssistOpsApi {
  constructor() {
    this.name = 'assistOpsApi';
    this.displayName = 'AssistOps API';
    this.properties = [
      { displayName: 'Base URL', name: 'baseUrl', type: 'string', default: 'http://api:8000', required: true },
      { displayName: 'Connector ID', name: 'connectorId', type: 'string', default: '', required: true },
      { displayName: 'Signing Secret', name: 'secret', type: 'string', typeOptions: { password: true }, default: '', required: true },
      { displayName: 'Tenant ID', name: 'tenantId', type: 'string', default: '', required: true },
      { displayName: 'User ID', name: 'userId', type: 'string', default: '', required: true },
    ];
  }
}
module.exports = { AssistOpsApi };
