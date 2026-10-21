'use strict';
(() => {
  const key = text => text.normalize('NFC').toLocaleLowerCase('es').trim().replace(/\s+/g, ' ');
  const labelId = text => `label:${encodeURIComponent(key(text))}`;
  const noteId = id => `note:${id}`;
  const findingId = id => `finding:${id}`;
  const documentFor = id => window.LAB_DATA.notes.find(n => n.id === id);
  function project(findings, { mode = 'labels', expanded = false, focusTag = '' } = {}) {
    const labels = new Map();
    for (const f of findings) for (const text of f.tags) {
      const k = key(text);
      if (!labels.has(k)) labels.set(k, { label: text, notes: new Set() });
      labels.get(k).notes.add(f.note);
    }
    const ranked = [...labels.values()].sort((a, b) => b.notes.size - a.notes.size || a.label.localeCompare(b.label));
    const rootTag = labels.get(key(focusTag))?.label || ranked[0]?.label || '';
    const visible = expanded ? findings : findings.filter(f => f.tags.some(t => key(t) === key(rootTag)));
    const nodes = new Map(), edges = new Map();
    function addNote(id) {
      const n = documentFor(id);
      nodes.set(noteId(id), { data: { id: noteId(id), kind: 'note', noteId: id, label: n.title, accessible: `Nota: ${n.title}` } });
    }
    if (mode === 'labels') {
      for (const f of visible) {
        addNote(f.note);
        for (const tag of f.tags.filter(t => expanded || key(t) === key(rootTag))) {
          const id = labelId(tag);
          nodes.set(id, { data: { id, kind: 'label', tag, label: tag, accessible: `Etiqueta: ${tag}` } });
          const edgeId = `membership:${f.note}:${id}`;
          if (!edges.has(edgeId)) edges.set(edgeId, { data: {
            id: edgeId, source: noteId(f.note), target: id, kind: 'membership',
            noteId: f.note, tag, findingIds: [], caption: '',
            accessible: `Conexión: ${documentFor(f.note).title} con ${tag}`,
          } });
          if (!edges.get(edgeId).data.findingIds.includes(f.id)) edges.get(edgeId).data.findingIds.push(f.id);
        }
      }
    } else {
      for (const f of visible) {
        addNote(f.note);
        nodes.set(findingId(f.id), { data: { id: findingId(f.id), kind: 'finding', findingId: f.id, label: f.title, accessible: `Hallazgo: ${f.title}` } });
        edges.set(`evidence:${f.id}`, { data: {
          id: `evidence:${f.id}`, source: noteId(f.note), target: findingId(f.id),
          kind: 'evidence', noteId: f.note, findingIds: [f.id], caption: '',
          accessible: `Cita de origen: ${f.title}`,
        } });
        if (mode === 'both') for (const tag of f.tags) {
          const id = labelId(tag);
          if (!nodes.has(id)) nodes.set(id, { data: { id, kind: 'label', tag, label: tag, accessible: `Etiqueta: ${tag}` } });
          const edgeId = `tagging:${f.id}:${id}`;
          edges.set(edgeId, { data: {
            id: edgeId, source: findingId(f.id), target: id, kind: 'tagging',
            findingIds: [f.id], tag: nodes.get(id).data.tag, caption: '',
            accessible: `Etiqueta ${nodes.get(id).data.tag} del hallazgo ${f.title}`,
          } });
        }
      }
      if (mode === 'findings') for (let i = 0; i < visible.length; i++) for (let j = i + 1; j < visible.length; j++) {
        const a = visible[i], b = visible[j];
        const shared = [...new Map(a.tags.filter(t => b.tags.some(other => key(t) === key(other))).map(t => [key(t), t])).values()];
        if (!shared.length) continue;
        const id = `shared:${[a.id, b.id].sort().join(':')}`;
        edges.set(id, { data: {
          id, source: findingId(a.id), target: findingId(b.id), kind: 'shared',
          tags: shared, findingIds: [a.id, b.id], caption: shared.join(' · '),
          accessible: `Comparten ${shared.join(' y ')}: ${a.title} y ${b.title}`,
        } });
      }
    }
    return {
      mode, rootTag, expanded, nodes: [...nodes.values()], edges: [...edges.values()],
      rootId: mode === 'findings' ? (visible[0] ? findingId(visible[0].id) : '') : labelId(rootTag),
      visibleFindingIds: visible.map(f => f.id), allFindingIds: findings.map(f => f.id),
    };
  }
  // Same vector lighting and palette as the existing emotion constellation.
  function orbImage(color) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 100 100"><defs><radialGradient id="a"><stop stop-color="${color}" stop-opacity=".28"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></radialGradient><radialGradient id="b" cx="28%" cy="24%" r="82%"><stop stop-color="#f5f4dd"/><stop offset=".28" stop-color="${color}"/><stop offset=".65" stop-color="${color}"/><stop offset="1" stop-color="#172b2c"/></radialGradient><radialGradient id="c" cx="30%" cy="22%" r="70%"><stop stop-color="#fff" stop-opacity=".75"/><stop offset=".45" stop-color="#fff" stop-opacity="0"/></radialGradient><radialGradient id="d"><stop stop-color="#020b0c" stop-opacity=".5"/><stop offset="1" stop-color="#020b0c" stop-opacity="0"/></radialGradient></defs><circle cx="50" cy="48" r="49" fill="url(#a)"/><ellipse cx="53" cy="83" rx="34" ry="12" fill="url(#d)"/><circle cx="50" cy="46" r="33" fill="url(#b)" stroke="${color}" stroke-opacity=".6" stroke-width=".7"/><circle cx="50" cy="46" r="33" fill="url(#c)"/><path d="M27 34a27 27 0 0 1 33-12" fill="none" stroke="#fff" stroke-opacity=".28" stroke-linecap="round"/></svg>`;
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  }
  const styles = [
    { selector: 'node', style: {
      shape: 'ellipse', width: 72, height: 72, 'background-opacity': 0,
      'background-image': orbImage('#b8d6ce'), 'background-fit': 'contain', 'background-clip': 'none',
      'border-width': 0, label: 'data(label)', color: '#eeeade', 'font-size': 13,
      'font-family': 'system-ui, sans-serif', 'text-wrap': 'wrap', 'text-max-width': 126,
      'text-overflow-wrap': 'whitespace', 'text-valign': 'bottom', 'text-margin-y': 5,
      'text-background-color': '#152326', 'text-background-opacity': .9,
      'text-background-padding': 3, 'text-background-shape': 'roundrectangle',
      'overlay-opacity': 0, 'min-zoomed-font-size': 8,
    } },
    { selector: 'node[kind = "label"]', style: { width: 68, height: 68, 'background-image': orbImage('#9bb68d') } },
    { selector: 'node[kind = "finding"]', style: { width: 68, height: 68, 'background-image': orbImage('#c7b078') } },
    { selector: 'node.root', style: { width: 88, height: 88, 'font-size': 14, 'font-weight': 'bold' } },
    { selector: 'node.combined', style: { 'font-size': 20, 'text-max-width': 165, 'min-zoomed-font-size': 0 } },
    { selector: 'node.combined.root', style: { 'font-size': 22 } },
    { selector: 'edge', style: {
      width: 1.3, 'curve-style': 'bezier', 'line-color': '#617a73',
      'target-arrow-color': '#617a73', 'target-arrow-shape': 'triangle', 'arrow-scale': .65,
      opacity: .75, 'overlay-opacity': 0, 'text-events': 'yes',
    } },
    { selector: 'edge[kind = "shared"]', style: {
      'target-arrow-shape': 'none', 'line-style': 'dashed', 'line-color': '#ae9c6f',
      'curve-style': 'unbundled-bezier', 'control-point-distances': 35, 'control-point-weights': .5,
      label: 'data(caption)', 'font-size': 13, color: '#d8c793', 'text-wrap': 'wrap',
      'text-max-width': 115, 'text-background-color': '#152326',
      'text-background-opacity': 1, 'text-background-padding': 4,
      'text-background-shape': 'roundrectangle', 'text-margin-y': -12, 'text-rotation': 'autorotate',
    } },
    { selector: 'node.picked', style: { 'border-width': 1, 'border-color': '#b8d6ce', 'overlay-color': '#b8d6ce', 'overlay-padding': 7, 'overlay-opacity': .12, 'font-weight': 'bold', 'z-index': 5 } },
    { selector: 'edge.picked', style: { width: 2.8, 'line-color': '#b8d6ce', 'target-arrow-color': '#b8d6ce', opacity: 1, 'z-index': 4 } },
  ];
  function initialPositions(model) {
    const findingNodes = model.nodes.filter(n => n.data.kind === 'finding');
    if (model.mode === 'findings' && findingNodes.length <= 3) {
      const positions = {}, anchors = [{x:0,y:-60},{x:-120,y:90},{x:120,y:90}];
      findingNodes.forEach((n, i) => { positions[n.data.id] = anchors[i]; });
      for (const {data:n} of model.nodes.filter(n => n.data.kind === 'note')) {
        const related = model.edges.filter(e => e.data.kind === 'evidence' && e.data.source === n.id).map(e => positions[e.data.target]);
        const x = related.reduce((sum,p) => sum+p.x,0)/related.length;
        const y = related.reduce((sum,p) => sum+p.y,0)/related.length;
        positions[n.id] = { x: x*1.25, y: y+(y<0 ? -120 : 120) };
      }
      return positions;
    }
    const ids = model.nodes.map(n => n.data.id), depth = new Map([[model.rootId, 0]]);
    for (let pass = 0; pass < ids.length; pass++) for (const { data: e } of model.edges) {
      if (depth.has(e.source) && !depth.has(e.target)) depth.set(e.target, depth.get(e.source) + 1);
      if (depth.has(e.target) && !depth.has(e.source)) depth.set(e.source, depth.get(e.target) + 1);
    }
    const positions = { [model.rootId]: { x: 0, y: 0 } };
    for (const level of [...new Set(ids.filter(id => id !== model.rootId).map(id => depth.get(id) || 3))].sort()) {
      const ring = ids.filter(id => id !== model.rootId && (depth.get(id) || 3) === level);
      ring.forEach((id, i) => {
        const angle = -Math.PI / 2 + i * Math.PI * 2 / ring.length + (level === 1 ? .23 : .66);
        const radius = level * 155;
        positions[id] = { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius };
      });
    }
    return positions;
  }
  function mount(host, model, onSelect) {
    const positions = initialPositions(model);
    const combinedLayout = { name: 'cose', animate: false, randomize: false, fit: true, padding: 38, nodeDimensionsIncludeLabels: true, nodeRepulsion: () => 12000, idealEdgeLength: () => 65, nodeOverlap: 20, gravity: 1 };
    const cy = window.cytoscape({
      container: host, elements: [...model.nodes.map(n => ({ ...n, classes: model.mode === 'both' ? 'combined' : '', position: positions[n.data.id] })), ...model.edges],
      style: styles, layout: model.mode === 'both' ? combinedLayout : { name: 'preset' }, minZoom: .15, maxZoom: 2.5,
      wheelSensitivity: .2, boxSelectionEnabled: false, autounselectify: true,
    });
    cy.getElementById(model.rootId).addClass('root');
    cy.on('tap', 'node, edge', event => onSelect(event.target.data()));
    let destroyed = false;
    let width = host.clientWidth, height = host.clientHeight;
    const observer = new ResizeObserver(() => {
      if (destroyed) return;
      const resized = host.clientWidth !== width || host.clientHeight !== height;
      width = host.clientWidth; height = host.clientHeight;
      cy.resize();
      if (resized) cy.fit(undefined, 38);
    });
    observer.observe(host);
    const frame = requestAnimationFrame(() => { if (!destroyed) { cy.resize(); cy.fit(undefined, 38); } });
    return {
      destroy() { destroyed = true; cancelAnimationFrame(frame); observer.disconnect(); cy.destroy(); },
      select(id) {
        cy.elements().removeClass('picked');
        const element = cy.getElementById(id);
        if (element.length) element.addClass('picked');
        else if (id.startsWith('finding:')) cy.edges().filter(e => e.data('findingIds')?.includes(id.slice(8))).addClass('picked');
      },
      zoom(factor) { const position = { x: cy.width() / 2, y: cy.height() / 2 }; cy.zoom({ level: Math.min(2.5, Math.max(.15, cy.zoom() * factor)), renderedPosition: position }); },
      fit() { cy.fit(undefined, 38); },
      arrange() { cy.layout(model.mode === 'both' ? combinedLayout : { name: 'cose', animate: false, randomize: false, fit: true, padding: 40, nodeDimensionsIncludeLabels: true, nodeRepulsion: () => 180000, idealEdgeLength: () => 160, componentSpacing: 100 }).run(); },
      exportPng() { return cy.png({ full: false, scale: 2, bg: '#152326' }); },
    };
  }
  window.LabGraph = { project, mount };
})();
