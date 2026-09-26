const { createHmac, randomUUID } = require('node:crypto');

// Identity is supplied by an administrator-owned credential, never by the webhook body.
function prepare(operation, input, credentials) {
  const fields = operation === 'submit'
    ? ['event_id', 'conversation_id', 'message', 'tool_call'] : ['receipt_id'];
  if (!input || typeof input !== 'object' || Array.isArray(input)
      || Object.keys(input).some((key) => !fields.includes(key))) {
    return null;
  }
  const required = operation === 'submit' ? ['event_id', 'conversation_id', 'message'] : ['receipt_id'];
  if (required.some((key) => typeof input[key] !== 'string' || !input[key].trim())) return null;
  return JSON.stringify({ ...input, tenant_id: credentials.tenantId,
    user_id: credentials.userId, source: 'webhook' });
}

async function request(operation, input, credentials, transport = fetch) {
  const body = prepare(operation, input, credentials);
  if (body === null) return { statusCode: 422, body: { error: 'invalid_input' }, retryAfter: '' };
  if (Buffer.byteLength(body) > 65536) {
    return { statusCode: 413, body: { error: 'payload_too_large' }, retryAfter: '' };
  }
  const base = new URL(credentials.baseUrl);
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password
      || base.search || base.hash || base.pathname !== '/') throw new Error('Invalid AssistOps base URL');
  const timestamp = String(Math.floor(Date.now() / 1000));
  const signature = createHmac('sha256', credentials.secret).update(`${timestamp}.${body}`).digest('hex');
  try {
    // Do not retry here: the caller retains its event ID and observes Retry-After.
    // Redirects are forbidden so the signed body cannot be forwarded to another host.
    const response = await transport(new URL(operation === 'submit' ? '/v1/events' : '/v1/events/status', base), {
      method: 'POST', body, redirect: 'error', signal: AbortSignal.timeout(10000),
      headers: { 'Content-Type': 'application/json', 'X-AssistOps-Connector': credentials.connectorId,
        'X-AssistOps-Timestamp': timestamp, 'X-AssistOps-Signature': `v1=${signature}`,
        'X-Correlation-ID': randomUUID() },
    });
    return { statusCode: response.status, body: await response.json(),
      retryAfter: response.headers.get('retry-after') || '' };
  } catch {
    // Native errors can include transport details; keep the public response generic.
    return { statusCode: 502, body: { error: 'assistops_unavailable' }, retryAfter: '1' };
  }
}

class AssistOps {
  constructor() {
    this.description = {
      displayName: 'AssistOps', name: 'assistOps', group: ['transform'], version: 1,
      description: 'Submit and query identity-scoped, signed AssistOps requests',
      defaults: { name: 'AssistOps' }, inputs: ['main'], outputs: ['main'],
      credentials: [{ name: 'assistOpsApi', required: true }],
      properties: [{ displayName: 'Operation', name: 'operation', type: 'options', default: 'submit',
        options: [{ name: 'Submit Event', value: 'submit' }, { name: 'Read Status', value: 'status' }] }],
    };
  }
  async execute() {
    const credentials = await this.getCredentials('assistOpsApi');
    const output = [];
    for (const [index, item] of this.getInputData().entries()) {
      const operation = this.getNodeParameter('operation', index);
      if (!['submit', 'status'].includes(operation)) throw new Error('Unsupported operation');
      output.push({ json: await request(operation, item.json.body, credentials), pairedItem: { item: index } });
    }
    return [output];
  }
}
module.exports = { AssistOps, prepare, request };
