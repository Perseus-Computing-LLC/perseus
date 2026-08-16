/* Perseus client error beacon — self-hosted, opt-out-free, minimal.
   Reports uncaught errors + unhandled promise rejections to the Perseus
   cloud-api collector (cloud-api.perseus.observer/api/report), which relays
   to the operator via self-hosted ntfy. No PII beyond message/source/line/
   page path/UA. Throttled + de-duplicated per page load; failures are silent. */
(function () {
  'use strict';
  var ENDPOINT = 'https://cloud-api.perseus.observer/api/report';
  if (location.protocol !== 'https:') return;
  var sent = [];
  var budget = 5;
  function noise(message) {
    return /ResizeObserver loop|Script error/i.test(message || '');
  }
  function send(record) {
    if (budget <= 0 || noise(record.message)) return;
    var key = record.message + '|' + (record.source || '') + '|' + (record.line || 0);
    if (sent.indexOf(key) !== -1) return;
    sent.push(key);
    budget -= 1;
    try {
      var payload = JSON.stringify({
        service: 'site',
        message: String(record.message || 'unknown error').slice(0, 500),
        source: String(record.source || '').slice(0, 200),
        line: Number(record.line) || 0,
        page: location.pathname.slice(0, 300),
        ua: String(navigator.userAgent || '').slice(0, 200)
      });
      if (navigator.sendBeacon) {
        navigator.sendBeacon(ENDPOINT, new Blob([payload], { type: 'application/json' }));
        return;
      }
      var xhr = new XMLHttpRequest();
      xhr.open('POST', ENDPOINT, true);
      xhr.setRequestHeader('Content-Type', 'application/json');
      xhr.send(payload);
    } catch (e) { /* silent */ }
  }
  window.addEventListener('error', function (event) {
    var src = String(event.filename || (event.target && event.target.src) || '');
    if (src.indexOf('chrome-extension://') === 0 || src.indexOf('moz-extension://') === 0) return;
    send({ message: event.message || 'resource load error', source: src, line: event.lineno || 0 });
  });
  window.addEventListener('unhandledrejection', function (event) {
    var reason = event.reason;
    var message = (reason && reason.message) ? String(reason.message) : String(reason);
    send({ message: 'unhandledrejection: ' + message.slice(0, 400), source: '', line: 0 });
  });
})();
