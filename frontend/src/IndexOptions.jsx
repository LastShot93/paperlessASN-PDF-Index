import React from 'react';
export const groupLabels = {tags: 'Tags', correspondent: 'Korrespondenten', year: 'Jahr', document_type: 'Dokumenttyp'};
export const defaults = {start: 1, end: 100, groups: ['tags', 'correspondent'], sort: 'title', title: 'Archivverzeichnis', selected_tags: null, tag_mode: 'multiple', tag_priority: [], year_desc: false, location_field: null, location_rules: [], correspondent_register: true, show_gaps: false, pdf_toc: true, new_group_page: false};
export function loadForm() {
  try {return {...defaults, ...JSON.parse(localStorage.getItem('asn-index-options') || '{}')};}
  catch {return {...defaults};}
}
export function normalizeForm(form) {
  return {...form, start: Number(form.start), end: Number(form.end), location_rules: form.location_rules.map(r => ({...r, start: Number(r.start), end: Number(r.end)}))};
}
export function GroupOptions({form, change}) {
  function updateGroup(depth, value) {
    const groups = [...form.groups];
    if (!value) groups.splice(depth);
    else {groups[depth] = value; for(let i=depth+1;i<groups.length;i++) if(groups[i]===value) {groups.splice(i); break;}}
    change('groups', groups);
  }
  return <>
    {Array.from({length: Math.min(4, form.groups.length + 1)}, (_, depth) => <div key={depth}>
      <label htmlFor={`group${depth+1}`} className="form-label">{['Erste', 'Zweite', 'Dritte', 'Vierte'][depth]} Gruppierung</label>
      <select id={`group${depth+1}`} className="form-select mb-3" value={form.groups[depth] || ''} onChange={e => updateGroup(depth, e.target.value)}>
        <option value="">{depth ? 'Keine weitere Gruppierung' : 'Keine Gruppierung'}</option>
        {Object.entries(groupLabels).filter(([key]) => !form.groups.slice(0,depth).includes(key)).map(([key,label]) => <option key={key} value={key}>{label}</option>)}
      </select>
    </div>)}
    {form.groups.includes('year') && <label className="d-block mb-3 small"><input type="checkbox" className="form-check-input me-2" checked={form.year_desc} onChange={e => change('year_desc',e.target.checked)}/>Jahresgruppen: neueste zuerst</label>}
  </>;
}
export function IndexOptions({form, change, metadata, connected, busy, ready, send}) {
  const tags = [...(metadata?.tags || [])].sort((a,b)=>a.name.localeCompare(b.name,'de'));
  const priority = [...form.tag_priority, ...tags.map(t=>t.id).filter(id=>!form.tag_priority.includes(id))];
  const selected = priority.filter(id=>form.selected_tags === null || form.selected_tags.includes(id));
  function move(id, direction) {
    const visibleIndex = selected.indexOf(id);
    const target = selected[visibleIndex + direction];
    if (target === undefined) return;
    const order = [...priority], i = order.indexOf(id), j = order.indexOf(target);
    [order[i],order[j]] = [order[j],order[i]]; change('tag_priority',order);
  }
  function ruleChange(i, key, value) {change('location_rules',form.location_rules.map((r,n)=>n===i ? {...r,[key]:value} : r));}
  return <details className="advanced-options mt-4"><summary>Register, Ablageorte und PDF-Optionen</summary><div className="pt-3">
    <button type="button" className="btn btn-outline-secondary btn-sm mb-3" disabled={!connected || busy || !ready} onClick={()=>send('metadata.get')}>Tags und Ablagefelder laden</button>
    {form.groups.includes('tags') && <>
      <h3 className="h6">Gruppierungs-Tags</h3>
      <label className="small d-block mb-2"><input type="checkbox" className="form-check-input me-2" checked={form.selected_tags === null} onChange={e=>change('selected_tags',e.target.checked ? null : tags.map(t=>t.id))}/>Alle Tags für die Gruppierung verwenden</label>
      {form.selected_tags !== null && <div className="tag-selection mb-3">{tags.length ? tags.map(tag=><label className="small d-block py-1" key={tag.id}><input type="checkbox" className="form-check-input me-2" checked={form.selected_tags.includes(tag.id)} onChange={e=>change('selected_tags',e.target.checked ? [...form.selected_tags,tag.id] : form.selected_tags.filter(id=>id!==tag.id))}/>{tag.name}</label>) : <p className="field-hint">Zuerst Tags laden. Ohne Auswahl werden alle Dokumente unter „Ohne passenden Tag“ geführt.</p>}</div>}
      <label htmlFor="tag-mode" className="form-label">Dokumente mit mehreren Tags</label><select id="tag-mode" className="form-select mb-2" value={form.tag_mode} onChange={e=>change('tag_mode',e.target.value)}><option value="multiple">Unter jedem passenden Tag aufführen</option><option value="priority">Einmal nach Tag-Priorität zuordnen</option></select>
      {form.tag_mode === 'priority' && <div className="mb-3"><p className="field-hint">Oberster passender Tag gewinnt. Nicht priorisierte Tags folgen alphabetisch.</p>{selected.map((id,i)=><div className="priority-row" key={id}><span>{i+1}. {tags.find(t=>t.id===id)?.name || `Tag #${id}`}</span><div><button type="button" className="btn btn-sm btn-outline-secondary" aria-label={`${tags.find(t=>t.id===id)?.name || id} nach oben`} disabled={i===0} onClick={()=>move(id,-1)}>↑</button><button type="button" className="btn btn-sm btn-outline-secondary ms-1" aria-label={`${tags.find(t=>t.id===id)?.name || id} nach unten`} disabled={i===selected.length-1} onClick={()=>move(id,1)}>↓</button></div></div>)}</div>}
      <p className="field-hint">Die Tag-Auswahl filtert keine Dokumente. Alle ursprünglichen Tags bleiben als Suchhinweise sichtbar.</p>
    </>}
    <h3 className="h6 mt-3">Physischer Ablageort</h3><label className="form-label" htmlFor="location-field">Paperless-Feld für den Ablageort</label><select id="location-field" className="form-select mb-2" value={form.location_field || ''} onChange={e=>change('location_field',e.target.value ? Number(e.target.value) : null)}><option value="">Kein Feld / nur ASN-Zuordnung</option>{form.location_field && !(metadata?.custom_fields || []).some(f=>f.id===form.location_field) && <option value={form.location_field}>Feld #{form.location_field} · Metadaten laden</option>}{(metadata?.custom_fields || []).map(field=><option key={field.id} value={field.id}>{field.name}</option>)}</select>
    <p className="field-hint">Text- und Auswahlfelder werden unterstützt. Fehlt ein Wert, gilt die ASN-Zuordnung unten.</p>
    {form.location_rules.map((rule,i)=><div className="location-rule mb-3" key={i}><div className="row g-2"><div className="col-6"><label className="form-label" htmlFor={`rule-start-${i}`}>ASN von</label><input id={`rule-start-${i}`} className="form-control" type="number" min="0" max="2147483647" required value={rule.start} onChange={e=>ruleChange(i,'start',e.target.value)}/></div><div className="col-6"><label className="form-label" htmlFor={`rule-end-${i}`}>ASN bis</label><input id={`rule-end-${i}`} className="form-control" type="number" min={rule.start || 0} max="2147483647" required value={rule.end} onChange={e=>ruleChange(i,'end',e.target.value)}/></div></div><label className="form-label mt-2" htmlFor={`rule-label-${i}`}>Ordner / Register</label><input id={`rule-label-${i}`} className="form-control" required maxLength={150} value={rule.label} placeholder="Ordner 3 / Versicherungen" onChange={e=>ruleChange(i,'label',e.target.value)}/><button type="button" className="btn btn-link btn-sm px-0" onClick={()=>change('location_rules',form.location_rules.filter((_,n)=>n!==i))}>Zuordnung entfernen</button></div>)}
    <button type="button" className="btn btn-outline-secondary btn-sm mb-3" disabled={form.location_rules.length>=100} onClick={()=>change('location_rules',[...form.location_rules,{start:form.start,end:form.end,label:''}])}>ASN-Ablageort hinzufügen</button>
    <h3 className="h6 mt-3">Zusätzliche Suchhilfen</h3>
    {[['correspondent_register','Alphabetisches Korrespondentenregister'],['show_gaps','ASN-Abgleich: nicht im API-Ergebnis vorhanden'],['pdf_toc','PDF-Inhaltsverzeichnis mit Seitenzahlen'],['new_group_page','Jede Hauptgruppe auf einer neuen PDF-Seite']].map(([key,label])=><label className="small d-block mb-2" key={key}><input type="checkbox" className="form-check-input me-2" checked={form[key]} onChange={e=>change(key,e.target.checked)}/>{label}</label>)}
    <p className="field-hint mb-0">PDF-Lesezeichen und Gruppen im Seitenkopf werden automatisch ergänzt. Deine Verzeichniseinstellungen bleiben in diesem Browser gespeichert.</p>
  </div></details>;
}
export function SearchAppendices({index}) {
  return <>
    {index.register?.length>0 && <section className="index-section"><h4>Korrespondentenregister</h4>{index.register.map(entry=><div className="register-entry" key={entry.name}><strong>{entry.name}</strong><span>ASN {entry.asns.join(', ')}</span></div>)}</section>}
    {index.config?.show_gaps && <section className="index-section"><h4>ASN-Abgleich</h4><p className="field-hint">{index.gap_count} ASN nicht im API-Ergebnis vorhanden. Nummern können unbenutzt sein oder dem API-Benutzer fehlen.</p><p className="small">{index.gaps.length ? index.gaps.map(r=>r.start===r.end ? r.start : `${r.start}–${r.end}`).join(', ') : 'Keine Lücken im API-Ergebnis.'}</p></section>}
  </>;
}
