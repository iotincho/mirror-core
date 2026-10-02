import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

// Synthetic records shaped like LinkReport.links, never personal workspace data.
const types = {
  SAME_REFERENT: { label: 'Mismo referente', color: '#a7b49a', temporal: false },
  IN_TENSION: { label: 'En tensión', color: '#e6a3a4', temporal: false },
  SHIFTS: { label: 'Cambio de postura', color: '#d9b977', temporal: true },
  REVISITS: { label: 'Retoma una idea', color: '#8cb5c5', temporal: true },
}
const themes = ['Pintura', 'Trabajo', 'Descanso', 'Aprendizaje', 'Amistades', 'Escritura']
const phrases = {
  Pintura: ['Quiero volver a pintar.', 'Hoy reservé un rato para pintar.', 'Antes postergaba pintar; hoy decidí hacerlo.', 'La pintura volvió a aparecer entre mis planes.'],
  Trabajo: ['Quiero reservar tiempo para el trabajo.', 'El trabajo ocupa más tiempo del que quiero.', 'Antes quería más trabajo; hoy prefiero reducirlo.', 'Volví a pensar en el lugar que tiene el trabajo.'],
  Descanso: ['Necesito tiempo para descansar.', 'Me cuesta frenar y descansar.', 'Antes postergaba el descanso; ahora lo priorizo.', 'Volví a pensar en cómo descansar mejor.'],
  Aprendizaje: ['Quiero dedicar tiempo a aprender.', 'Me cuesta sostener el tiempo de estudio.', 'Antes estudiaba de noche; ahora prefiero la mañana.', 'Retomé mi idea de hacer un curso.'],
  Amistades: ['Quiero ver más a mis amistades.', 'Me cuesta encontrar tiempo para vernos.', 'Antes esperaba que me llamaran; ahora propongo encuentros.', 'Volví a pensar en organizar una reunión.'],
  Escritura: ['Quiero volver a escribir.', 'Hoy dediqué un rato a escribir.', 'Antes buscaba publicar; ahora escribo para mí.', 'Retomé la idea de escribir un diario.'],
}
const docs = Array.from({ length: 200 }, (_, i) => {
  const theme = themes[Math.floor(i / 34) % themes.length]
  const quote = phrases[theme][i % 4]
  return { id: `doc-${i}`, title: i === 0 ? 'Volver a pintar' : `${theme} · nota ${i + 1}`, authored_at: new Date(Date.UTC(2026, 0, 1 + i)).toISOString(), content: quote, theme }
})
const byId = Object.fromEntries(docs.map(d => [d.id, d]))
const links = []
const linkKeys = new Set()
function addLink(a, b, type) {
  if (a >= docs.length || b >= docs.length || a === b) return
  const [source, target] = [a, b].sort((x, y) => x - y)
  const key = `${source}:${target}:${type}`
  if (linkKeys.has(key)) return
  linkKeys.add(key)
  links.push({ id: `link-${links.length}`, source_document_id: docs[source].id, target_document_id: docs[target].id, source_claim_id: `run-${source}:claim:1`, target_claim_id: `run-${target}:claim:1`, relation_type: type, source_evidence: [{ quote: docs[source].content, start_line: 1, end_line: 1 }], target_evidence: [{ quote: docs[target].content, start_line: 1, end_line: 1 }], similarity: .81, profile: 'link-v1' })
}
for (let i = 0; i < docs.length; i++) {
  addLink(i, i + 1, 'REVISITS')
  addLink(i, i + 3, 'SHIFTS')
  addLink(i, i + 8, 'SAME_REFERENT')
  addLink(i, i + 13, 'IN_TENSION')
}
for (let j = 1; j < 34; j++) addLink(0, j, Object.keys(types)[j % 4])
const date = value => new Intl.DateTimeFormat('es-AR', { day: 'numeric', month: 'short' }).format(new Date(value))

function App() {
  const [focus, setFocus] = useState('doc-0')
  const [visible, setVisible] = useState(['doc-0'])
  const [filter, setFilter] = useState('ALL')
  const [selectedNode, setSelectedNode] = useState('doc-0')
  const [selectedLink, setSelectedLink] = useState(null)
  const [mode, setMode] = useState('graph')
  const [notice, setNotice] = useState('')
  const [metrics, setMetrics] = useState('')
  const host = useRef(null)
  const engine = useRef(null)
  const allowed = link => filter === 'ALL' || link.relation_type === filter
  const neighbors = id => [...new Set(links.filter(allowed).filter(l => l.source_document_id === id || l.target_document_id === id).map(l => l.source_document_id === id ? l.target_document_id : l.source_document_id))]
  const visibleSet = new Set(visible)
  const shownLinks = links.filter(allowed).filter(l => visibleSet.has(l.source_document_id) && visibleSet.has(l.target_document_id))
  const nodeLinks = links.filter(allowed).filter(l => l.source_document_id === selectedNode || l.target_document_id === selectedNode)
  const hidden = neighbors(selectedNode).filter(id => !visibleSet.has(id))
  function expand(id) {
    const extra = neighbors(id).filter(n => !visibleSet.has(n)).slice(0, Math.min(10, 40 - visible.length))
    if (!extra.length) { setNotice(visible.length >= 40 ? 'Llegaste al límite de 40 notas. Centrá la vista en otra nota para seguir.' : 'Ya se muestran sus conexiones disponibles.'); return }
    setVisible(prev => [...new Set([...prev, ...extra])]); setNotice(`Se agregaron ${extra.length} notas al vecindario.`)
  }
  function center(id, nextFilter = filter) {
    const adjacent = [...new Set(links.filter(l => nextFilter === 'ALL' || l.relation_type === nextFilter).filter(l => l.source_document_id === id || l.target_document_id === id).map(l => l.source_document_id === id ? l.target_document_id : l.source_document_id))]
    setFocus(id); setVisible([id, ...adjacent.slice(0, 10)]); setSelectedNode(id); setSelectedLink(null); setNotice('')
  }
  useEffect(() => { center('doc-0') }, [])
  useEffect(() => {
    if (mode !== 'graph' || !host.current) return
    const start = performance.now()
    const cy = window.cytoscape({
      container: host.current,
      elements: [
        ...visible.map(id => ({ data: { id, label: `${byId[id].title}\n${date(byId[id].authored_at)}`, color: byId[id].theme === 'Pintura' ? '#8cb5c5' : '#a7b49a' }, classes: id === focus ? 'focus' : '' })),
        ...shownLinks.map(l => ({ data: { id: l.id, source: l.source_document_id, target: l.target_document_id, color: types[l.relation_type].color, arrow: types[l.relation_type].temporal ? 'triangle' : 'none' } })),
      ],
      style: [
        { selector: 'node', style: { 'shape': 'round-rectangle', 'width': 135, 'height': 58, 'background-color': '#1b2628', 'border-color': 'data(color)', 'border-width': 1, 'label': 'data(label)', 'color': '#f0eee6', 'font-size': 11, 'font-family': 'Manrope, system-ui, sans-serif', 'text-wrap': 'wrap', 'text-max-width': 120, 'text-valign': 'center', 'text-halign': 'center' } },
        { selector: 'node.focus', style: { 'background-color': '#243439', 'border-width': 3, 'border-color': '#8cb5c5', 'font-weight': 'bold' } },
        { selector: 'edge', style: { 'width': 1.4, 'line-color': 'data(color)', 'target-arrow-color': 'data(color)', 'target-arrow-shape': 'data(arrow)', 'curve-style': 'bezier', 'opacity': .65 } },
        { selector: '.muted', style: { opacity: .13 } },
        { selector: '.picked', style: { 'opacity': 1, 'width': 3.4, 'border-width': 3 } },
      ],
      layout: { name: 'concentric', animate: false, padding: 45, minNodeSpacing: 34, concentric: node => node.id() === focus ? 2 : 1, levelWidth: () => 1, avoidOverlap: true },
      minZoom: .2, maxZoom: 2.5, wheelSensitivity: .2,
    })
    engine.current = cy
    setMetrics(`${Math.round(performance.now() - start)} ms de creación y distribución`)
    cy.on('tap', 'node', event => { setSelectedNode(event.target.id()); setSelectedLink(null) })
    cy.on('tap', 'edge', event => { setSelectedLink(links.find(l => l.id === event.target.id())); setNotice('') })
    const observer = new ResizeObserver(() => { cy.resize() })
    observer.observe(host.current)
    return () => { observer.disconnect(); cy.destroy(); engine.current = null }
  }, [visible, filter, focus, mode])
  useEffect(() => {
    const cy = engine.current
    if (!cy) return
    cy.elements().removeClass('muted picked')
    if (selectedLink) {
      cy.elements().addClass('muted')
      cy.getElementById(selectedLink.id).removeClass('muted').addClass('picked')
      cy.getElementById(selectedLink.source_document_id).removeClass('muted')
      cy.getElementById(selectedLink.target_document_id).removeClass('muted')
    } else {
      cy.getElementById(selectedNode).addClass('picked')
    }
  }, [selectedLink, selectedNode, visible, mode])

  return <main className="constellation-shell">
    <header className="app-bar"><a className="brand" href="#" onClick={e => e.preventDefault()}><img className="brand-mark" src="/el-espejo-mark.png" alt=""/>El Espejo</a><span className="prototype-tag">VISTA PREVIA</span></header>
    <div className="intro"><span className="eyebrow">CONSTELACIÓN</span><h1>Seguí el hilo de tus notas</h1><p>Elegí una nota y descubrí sus conexiones, paso a paso.</p></div>
    <section className="choose"><label>Empezar desde<select value={focus} onChange={e => center(e.target.value)}>{docs.map(d => <option key={d.id} value={d.id}>{d.title} · {date(d.authored_at)}</option>)}</select></label><div className="mode-switch"><button aria-pressed={mode === 'graph'} onClick={() => setMode('graph')}>Grafo</button><button aria-pressed={mode === 'list'} onClick={() => setMode('list')}>Lista</button></div></section>
    <div className="filters">{[['ALL', 'Todas'], ...Object.entries(types).map(([k,v]) => [k,v.label])].map(([key,label]) => <button key={key} aria-pressed={filter === key} onClick={() => { setFilter(key); center(focus, key) }}>{key !== 'ALL' && <i style={{background:types[key].color}}/>}{label}</button>)}</div>
    <div className="workspace"><section className="graph-panel" aria-label="Vecindario de notas">
      <div className="graph-top"><span>{visible.length} de {docs.length} notas · {shownLinks.length} vínculos</span><span>Máximo visible: 40</span></div>
      {mode === 'graph' ? <><div className="graph-host" ref={host}/><div className="graph-controls"><button aria-label="Acercar" onClick={() => engine.current?.zoom(engine.current.zoom() * 1.25)}>+</button><button aria-label="Alejar" onClick={() => engine.current?.zoom(engine.current.zoom() / 1.25)}>−</button><button onClick={() => engine.current?.fit(undefined, 40)}>Ajustar</button></div><p className="gesture-hint">Tocá una nota o conexión · Arrastrá para moverte</p></> : <div className="links-list">{shownLinks.length === 0 && <p>No hay vínculos visibles para este filtro.</p>}{shownLinks.map(l => <button key={l.id} onClick={() => setSelectedLink(l)}><small style={{color:types[l.relation_type].color}}>{types[l.relation_type].label}</small><span>{byId[l.source_document_id].title} {types[l.relation_type].temporal ? '→' : '↔'} {byId[l.target_document_id].title}</span></button>)}</div>}
      <div className="legend"><span>— Vínculo simétrico</span><span>→ Hilo temporal</span></div>
    </section><aside className="detail" aria-live="polite">
      {selectedLink ? <><span className="eyebrow">CONEXIÓN SUGERIDA</span><h2>{types[selectedLink.relation_type].label}</h2><p className="direction">{types[selectedLink.relation_type].temporal ? 'Lectura: de la nota anterior a la posterior.' : 'La relación puede leerse desde ambos extremos.'}</p>{['source','target'].map(side => {const d = byId[selectedLink[`${side}_document_id`]]; return <article className="quote" key={side}><small>{date(d.authored_at)} · {d.title}</small><blockquote>“{selectedLink[`${side}_evidence`][0].quote}”</blockquote><button onClick={() => { setSelectedNode(d.id); setSelectedLink(null) }}>Ver conexiones de esta nota →</button></article>})}<p className="detail-footnote">Las citas son ejemplos sintéticos. La relación no es una afirmación sobre vos.</p><button className="secondary" onClick={() => setSelectedLink(null)}>Volver a la nota</button></> : <><span className="eyebrow">NOTA SELECCIONADA</span><h2>{byId[selectedNode].title}</h2><p className="direction">{date(byId[selectedNode].authored_at)} · {nodeLinks.length} conexiones en este ejemplo</p><article className="quote"><blockquote>“{byId[selectedNode].content}”</blockquote></article><button className="primary" disabled={!hidden.length || visible.length >= 40} onClick={() => expand(selectedNode)}>{hidden.length ? `Mostrar hasta 10 más (${hidden.length} pendientes)` : 'Todas sus conexiones están visibles'}</button><button className="secondary" onClick={() => center(selectedNode)}>Centrar el grafo en esta nota</button><p className="detail-footnote">Cada expansión agrega hasta 10 notas. Para continuar al llegar a 40, centrá la vista en otra nota.</p><div className="mini-links">{nodeLinks.slice(0, 5).map(l => <button key={l.id} onClick={() => setSelectedLink(l)}><i style={{background:types[l.relation_type].color}}/>{types[l.relation_type].label}<span>›</span></button>)}</div></>}
      {notice && <p className="notice" role="status">{notice}</p>}
    </aside></div>
    <footer className="preview-footer"><span>Datos sintéticos · {links.length} vínculos · Cytoscape.js {window.cytoscape.version}</span><span>{metrics}</span></footer>
    <nav className="bottom-nav"><span>✎ Escribir</span><span>✦ Explorar</span><span className="nav-current">⌘ Constelación</span></nav>
  </main>
}
createRoot(document.getElementById('root')).render(<App/> )
