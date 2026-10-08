import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import 'bootstrap/dist/css/bootstrap.min.css';
import './style.css';

import {groupLabels, loadForm, normalizeForm, GroupOptions, IndexOptions, SearchAppendices} from './IndexOptions';
const formatDate = value => value ? value.split('-').reverse().join('.') : '—';
function App() {
  const socket = useRef(null), reconnect = useRef(null);
  const [connected, setConnected] = useState(false), [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState(null), [showSettings, setShowSettings] = useState(false);
  const [url, setUrl] = useState(''), [token, setToken] = useState(''), [clearToken, setClearToken] = useState(false);
  const [notice, setNotice] = useState(null), [progress, setProgress] = useState(null), [index, setIndex] = useState(null);
  const [form, setForm] = useState(loadForm);
  const [metadata, setMetadata] = useState(null);
  useEffect(() => {try {localStorage.setItem('asn-index-options', JSON.stringify(form));} catch {}}, [form]);
  useEffect(() => {
    let alive = true;
    function connect() {
      const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
      socket.current = ws;
      ws.onopen = () => {if (alive) {setConnected(true); setIndex(null);}};
      ws.onclose = () => {if (alive) {setConnected(false); setBusy(false); setProgress(null); reconnect.current = setTimeout(connect, 2500);}};
      ws.onmessage = event => {
        const {type, data, id} = JSON.parse(event.data);
        if (type === 'settings') {
          setSettings(data); setUrl(data.url); setToken(''); setClearToken(false);
          setMetadata(null);
          if (id) setNotice({kind: 'success', text: 'Einstellungen gespeichert.'});
        } else if (type === 'metadata') {setMetadata(data);}
        else if (type === 'error') {setNotice({kind: 'danger', text: data}); setProgress(null);}
        else if (type === 'connection') setNotice({kind: 'success', text: data.message});
        else if (type === 'progress') setProgress(data);
        else if (type === 'index') {setIndex(data); setProgress(null); if (!data.count) setNotice({kind: 'info', text: 'Keine Dokumente im gewählten ASN-Bereich gefunden.'});}
        else if (type === 'pdf') {
          const bytes = Uint8Array.from(atob(data.content), c => c.charCodeAt(0));
          const href = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'}));
          const a = document.createElement('a'); a.href = href; a.download = data.filename; a.click();
          setTimeout(() => URL.revokeObjectURL(href), 10000);
        }
        if (type !== 'progress' && id) setBusy(false);
      };
    }
    connect();
    return () => {alive = false; clearTimeout(reconnect.current); socket.current?.close();};
  }, []);
  function send(type, data) {
    if (!connected || busy) return;
    setBusy(true); setNotice(null);
    socket.current.send(JSON.stringify({type, data, id: crypto.randomUUID()}));
  }
  function change(key, value) {setForm(old => ({...old, [key]: value}));}
  const ready = settings?.url && settings?.has_token;
  const stale = index && JSON.stringify(normalizeForm(form)) !== JSON.stringify(index.config);
  return <>
    <header className="app-header"><div className="container-xl d-flex align-items-center justify-content-between gap-3"><a className="brand" href="/"> <span className="brand-symbol">P</span><span>paperless<span className="brand-sub">ASN INDEX</span></span></a><div className="d-flex align-items-center gap-3"><span className={`connection ${connected ? 'online' : ''}`}><span/> {connected ? 'Verbunden' : 'Verbindung wird hergestellt'}</span><button className="btn btn-outline-light btn-sm" onClick={() => setShowSettings(!showSettings)} aria-expanded={showSettings}>Einstellungen</button></div></div></header>
    <main className="container-xl py-5">
      <div className="intro"><div className="eyebrow">DEIN DIGITALES ARCHIV. AUF PAPIER.</div><h1>Jedes Dokument.<br/><span>Einfach wiederfinden.</span></h1><p>Erstelle ein übersichtliches Inhaltsverzeichnis für deine Archivordner —<br className="d-none d-md-block"/> mit ASN, Dokumenttitel und Korrespondent aus Paperless-ngx.</p></div>
      {notice && <div role="alert" className={`alert alert-${notice.kind} d-flex justify-content-between`}>{notice.text}<button type="button" className="btn-close" aria-label="Meldung schließen" onClick={() => setNotice(null)}/></div>}
      {showSettings && <section className="card settings-panel mb-4"><div className="card-body p-4"><div className="d-flex justify-content-between"><h2 className="h5">Verbindung zu Paperless</h2><button className="btn-close" aria-label="Einstellungen schließen" onClick={() => setShowSettings(false)}/></div><form onSubmit={e => {e.preventDefault(); setIndex(null); send('settings.save', {url, token: token || null, clear_token: clearToken});}}><div className="row g-3 mt-1"><div className="col-md-7"><label htmlFor="url" className="form-label">Paperless-URL</label><input id="url" type="url" required className="form-control" value={url} disabled={settings?.url_locked || busy} onChange={e => setUrl(e.target.value)} placeholder="https://paperless.example.de"/><small className="text-secondary">{settings?.url_locked ? 'Über Docker Compose vorgegeben.' : 'Basis-URL oder vollständige URL mit /api/.'}</small></div><div className="col-md-5"><label htmlFor="token" className="form-label">API-Key</label><input id="token" type="password" autoComplete="new-password" className="form-control" value={token} disabled={settings?.token_locked || busy || clearToken} onChange={e => setToken(e.target.value)} placeholder={settings?.has_token ? 'Key vorhanden · leer lassen zum Beibehalten' : 'Paperless API-Token'}/><small className="text-secondary">{settings?.token_locked ? 'Aus .env geladen. Bleibt ausschließlich im Backend.' : 'Wird nur im Backend gespeichert.'}</small>{settings?.has_token && !settings?.token_locked && <label className="d-block mt-2"><input type="checkbox" className="form-check-input me-2" checked={clearToken} disabled={busy} onChange={e => setClearToken(e.target.checked)}/>Gespeicherten API-Key entfernen</label>}</div></div><div className="d-flex gap-2 mt-3"><button className="btn btn-primary" disabled={!connected || busy}>Speichern</button><button type="button" className="btn btn-outline-secondary" disabled={!connected || busy || !ready} onClick={() => send('connection.test')}>Gespeicherte Verbindung testen</button></div></form></div></section>}
      {!ready && settings && !showSettings && <div className="setup-hint mb-4">Verbinde zuerst dein Paperless-Archiv. <button className="btn btn-link p-0" onClick={() => setShowSettings(true)}>Einstellungen öffnen →</button></div>}
      <div className="row g-4 align-items-start"><div className="col-lg-4"><section className="card configuration"><div className="card-body p-4"><div className="eyebrow mb-2">01 / KONFIGURATION</div><h2 className="h4 mb-4">Dein Archivbereich</h2><form onSubmit={e => {e.preventDefault(); setIndex(null); send('index.generate', normalizeForm(form));}}><fieldset disabled={busy}><label className="form-label" htmlFor="title">Titel des Verzeichnisses</label><input id="title" className="form-control mb-4" value={form.title} maxLength={150} required onChange={e => change('title', e.target.value)}/><div className="row g-3 mb-2"><div className="col-6"><label className="form-label" htmlFor="start">ASN von</label><input id="start" type="number" min="0" max="2147483647" required className="form-control" value={form.start} onChange={e => change('start', e.target.value)}/></div><div className="col-6"><label className="form-label" htmlFor="end">ASN bis</label><input id="end" type="number" min={form.start || 0} max="2147483647" required className="form-control" value={form.end} onChange={e => change('end', e.target.value)}/></div></div><p className="field-hint mb-4">Beide Grenzen sind eingeschlossen.</p><GroupOptions form={form} change={change}/><label htmlFor="sort" className="form-label">Dokumente sortieren nach</label><select id="sort" className="form-select" value={form.sort} onChange={e => change('sort', e.target.value)}><option value="title">Titel · A–Z</option><option value="asn">ASN · aufsteigend</option><option value="date">Datum · älteste zuerst</option><option value="date_desc">Datum · neueste zuerst</option></select><div className="group-preview my-4">{[...form.groups.map(g => groupLabels[g]), {title: 'A–Z', asn: 'ASN ↑', date: 'Datum ↑', date_desc: 'Datum ↓'}[form.sort]].join(' → ')}</div><IndexOptions form={form} change={change} metadata={metadata} connected={connected} busy={busy} ready={ready} send={send}/><button className="btn btn-primary w-100 py-3 mt-4" disabled={!connected || !ready || busy}>{busy ? 'Wird verarbeitet …' : 'Verzeichnis erstellen →'}</button></fieldset></form>{progress && <div className="mt-3" role="status"><div className="progress" style={{height: 6}}><div className="progress-bar" style={{width: `${progress.total ? Math.min(100, progress.loaded / progress.total * 100) : 0}%`}}/></div><small className="text-secondary">{progress.loaded} von {progress.total} Dokumenten geladen</small></div>}<p className="field-hint mt-3 mb-0">Dokumente ohne ASN werden ausgelassen. Tag-Auswahl und Priorität bestimmen die Zuordnung zu den Registern.</p></div></section></div>
      <div className="col-lg-8"><section className="card preview"><div className="preview-toolbar d-flex justify-content-between align-items-center gap-3"><div><div className="eyebrow">02 / VORSCHAU</div><h2 className="h5 mb-0 mt-1">Dein Inhaltsverzeichnis</h2></div><button className="btn btn-primary" disabled={!index || busy || !connected || stale} onClick={() => send('index.pdf')}>PDF herunterladen ↓</button></div>{stale && <div className="alert alert-warning m-3">Konfiguration geändert. Erstelle das Verzeichnis erneut, um das aktuelle PDF zu laden.</div>}{index ? <div className="paper"><div className="paper-kicker">ARCHIV / INDEX</div><h3>{index.title}</h3><div className="paper-meta">ASN {index.start}–{index.end}<span>{index.count} Dokumente · {new Date(index.generated_at).toLocaleDateString('de-DE')}</span></div>{!index.count && <p className="text-secondary py-4">Keine Dokumente in diesem Bereich.</p>}{index.sections.map((section, n) => <div className="index-section" key={n}>{section.path.length > 0 && <h4>{section.path.map((label, i) => <React.Fragment key={i}>{i > 0 && <span className="path-divider"> / </span>}{label}</React.Fragment>)}</h4>}<div className="table-responsive"><table className="table index-table"><thead><tr><th>ASN</th><th>Dokument</th><th>Datum</th></tr></thead><tbody>{section.documents.map(doc => <tr key={doc.id}><td><span className="asn">{doc.asn}</span></td><td>{doc.title}<small>{doc.correspondent} · {doc.document_type}</small>{doc.tags.length>0 && <small>Tags: {doc.tags.join(', ')}</small>}{doc.location && <small className="location-hint">Ablage: {doc.location}</small>}</td><td className="text-nowrap text-secondary">{formatDate(doc.date)}</td></tr>)}</tbody></table></div></div>)}<SearchAppendices index={index}/></div> : <div className="empty-preview"><div className="document-icon"><span/><span/><span/></div><h3>Ordnung beginnt hier.</h3><p>Wähle deinen ASN-Bereich und die Gruppierung.<br/>Dein Verzeichnis erscheint anschließend hier.</p><span className="format-badge">A4 · PDF · bereit zum Abheften</span></div>}</section><p className="field-hint mt-3 text-center">Die Vorschau zeigt die Inhalte. Seitenumbrüche entstehen beim PDF-Export.</p></div></div>
      <footer>Paperless ASN Index <span>Ein Platz für jedes Dokument.</span></footer>
    </main>
  </>;
}
createRoot(document.getElementById('root')).render(<App/>);
