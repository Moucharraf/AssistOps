const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHmac } = require('node:crypto');
const { prepare, request } = require('./nodes/AssistOps/AssistOps.node');
const credentials = { baseUrl: 'http://api:8000', connectorId: 'n8n-demo',
  secret: 'test-secret', tenantId: 'demo', userId: 'user-001' };
const input = { event_id: 'event-1', conversation_id: 'conversation-1', message: 'Facture égarée' };

test('webhook cannot choose an identity, destination or approval operation', () => {
  for (const field of ['user_id', 'tenant_id', 'source', 'baseUrl', 'decision', 'secret']) {
    assert.equal(prepare('submit', { ...input, [field]: 'untrusted' }, credentials), null);
  }
  for (const invalid of [null, [], 'text', {}, { ...input, event_id: '' }]) {
    assert.equal(prepare('submit', invalid, credentials), null);
  }
});

test('HMAC covers the exact UTF-8 body; upstream ID survives retries', async () => {
  const bodies = [];
  const transport = async (url, options) => {
    assert.equal(url.href, 'http://api:8000/v1/events');
    const timestamp = options.headers['X-AssistOps-Timestamp'];
    const expected = createHmac('sha256', credentials.secret).update(`${timestamp}.${options.body}`).digest('hex');
    assert.equal(options.headers['X-AssistOps-Signature'], `v1=${expected}`);
    assert.equal(options.redirect, 'error');
    assert.equal(JSON.parse(options.body).user_id, 'user-001');
    bodies.push(options.body);
    return new Response('{"duplicate":true}', { status: 202 });
  };
  await request('submit', input, credentials, transport);
  await request('submit', input, credentials, transport);
  assert.equal(bodies[0], bodies[1]);
});

test('rate limits propagate without hidden retries', async () => {
  let calls = 0;
  const result = await request('status', { receipt_id: 'receipt' }, credentials, async () => {
    calls++;
    return new Response('{"error":"rate_limited"}', { status: 429, headers: { 'Retry-After': '7' } });
  });
  assert.equal(calls, 1);
  assert.equal(result.statusCode, 429);
  assert.equal(result.retryAfter, '7');
});

test('invalid and oversized requests never reach the API', async () => {
  const forbidden = async () => { assert.fail('Transport must not be called'); };
  assert.equal((await request('submit', {}, credentials, forbidden)).statusCode, 422);
  assert.equal((await request('submit', { ...input, message: 'é'.repeat(40000) }, credentials, forbidden)).statusCode, 413);
});

test('network exceptions never expose credentials or transport internals', async () => {
  const result = await request('submit', input, credentials, async () => { throw new Error(credentials.secret); });
  assert.equal(result.statusCode, 502);
  assert.ok(!JSON.stringify(result).includes(credentials.secret));
});
