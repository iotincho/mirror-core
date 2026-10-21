'use strict';
(() => {
  const key = text => text.normalize('NFC').toLocaleLowerCase('es').trim().replace(/\s+/g, ' ');
  const labelId = text => `label:${encodeURIComponent(key(text))}`;
  const noteId = id => `note:${id}`;
  const findingId = id => `finding:${id}`;
  const documentFor = id => window.LAB_DATA.notes.find(n => n.id === id);
  function project(findings, { visibility = {}, expanded = false, focusTag = '', revealedFindingIds = null } = {}) {
    const shown = { note: true, finding: true, label: true, ...visibility };
    if (!Object.values(shown).some(Boolean)) shown.label = true;
    const labels = new Map();
    for (const f of findings) for (const text of f.tags) {
      const k = key(text);
      if (!labels.has(k)) labels.set(k, { label: text, notes: new Set() });
      labels.get(k).notes.add(f.note);
    }
    const ranked = [...labels.values()].sort((a, b) => b.notes.size - a.notes.size || a.label.localeCompare(b.label));
    const rootTag = labels.get(key(focusTag))?.label || ranked[0]?.label || '';
    const revealed = revealedFindingIds ? new Set(revealedFindingIds) : null;
    const visible = revealed ? findings.filter(f => revealed.has(f.id)) : expanded ? findings : findings.filter(f => f.tags.some(t => key(t) === key(rootTag)));
    const nodes = new Map(), baseEdges = new Map(), edges = new Map();
    const addEdge = (target, data) => target.set(data.id, { data });
    for (const f of visible) {
      const n = documentFor(f.note);
      nodes.set(noteId(f.note), { data: { id: noteId(f.note), kind: 'note', noteId: f.note, label: n.title, accessible: `Nota: ${n.title}` } });
      nodes.set(findingId(f.id), { data: { id: findingId(f.id), kind: 'finding', findingId: f.id, label: f.title, accessible: `Hallazgo: ${f.title}` } });
      addEdge(baseEdges, {
        id: `evidence:${f.id}`, source: noteId(f.note), target: findingId(f.id),
        kind: 'evidence', noteId: f.note, findingIds: [f.id], caption: '',
        accessible: `Cita de origen: ${f.title}`,
      });
      for (const text of f.tags) {
        const tag = labels.get(key(text)).label, id = labelId(tag);
        if (!nodes.has(id)) nodes.set(id, { data: { id, kind: 'label', tag, label: tag, accessible: `Etiqueta: ${tag}` } });
        addEdge(baseEdges, {
          id: `tagging:${f.id}:${id}`, source: findingId(f.id), target: id, kind: 'tagging',
          findingIds: [f.id], tag, caption: '', accessible: `Etiqueta ${tag} del hallazgo ${f.title}`,
        });
        if (shown.note && shown.label && !shown.finding) {
          const edgeId = `membership:${f.note}:${id}`;
          if (!edges.has(edgeId)) addEdge(edges, {
            id: edgeId, source: noteId(f.note), target: id, kind: 'membership', projected: true,
            noteId: f.note, tag, findingIds: [], caption: '',
            accessible: `Conexión resumida: ${n.title} con ${tag}`,
          });
          if (!edges.get(edgeId).data.findingIds.includes(f.id)) edges.get(edgeId).data.findingIds.push(f.id);
        }
      }
    }
    for (const { data: e } of baseEdges.values()) if (shown[nodes.get(e.source).data.kind] && shown[nodes.get(e.target).data.kind]) addEdge(edges, e);
    // Only summarize paths with a known meaning. Hiding a layer never invents equivalence.
    if (shown.finding && !shown.label) {
      for (let i = 0; i < visible.length; i++) for (let j = i + 1; j < visible.length; j++) {
        const a = visible[i], b = visible[j];
        const shared = [...new Map(a.tags.filter(t => b.tags.some(other => key(t) === key(other))).map(t => [key(t), labels.get(key(t)).label])).values()];
        if (shared.length) addEdge(edges, {
          id: `shared:${[a.id, b.id].sort().join(':')}`, source: findingId(a.id), target: findingId(b.id),
          kind: 'shared', projected: true, tags: shared, findingIds: [a.id, b.id], caption: shared.join(' · '),
          accessible: `Comparten ${shared.join(' y ')}: ${a.title} y ${b.title}`,
        });
      }
    }
    if (shown.note && !shown.finding && !shown.label) {
      const noteIds = [...new Set(visible.map(f => f.note))];
      for (let i = 0; i < noteIds.length; i++) for (let j = i + 1; j < noteIds.length; j++) {
        const a = noteIds[i], b = noteIds[j];
        const own = visible.filter(f => f.note === a), other = visible.filter(f => f.note === b);
        const shared = [...new Map(own.flatMap(f => f.tags).filter(t => other.some(f => f.tags.some(u => key(u) === key(t)))).map(t => [key(t), labels.get(key(t)).label])).values()];
        const matches = [...own, ...other].filter(f => f.tags.some(t => shared.some(u => key(u) === key(t))));
        if (shared.length) addEdge(edges, {
          id: `note-shared:${a}:${b}`, source: noteId(a), target: noteId(b), kind: 'note-shared', projected: true,
          tags: shared, findingIds: matches.map(f => f.id), caption: shared.join(' · '),
          accessible: `Notas que comparten ${shared.join(' y ')}: ${documentFor(a).title} y ${documentFor(b).title}`,
        });
      }
    }
    if (shown.label && !shown.note && !shown.finding) for (const f of visible) {
      const ids = [...new Set(f.tags.map(labelId))].sort();
      for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
        const a = nodes.get(ids[i]).data, b = nodes.get(ids[j]).data;
        const id = `label-shared:${a.id}:${b.id}`;
        if (!edges.has(id)) addEdge(edges, {
          id, source: a.id, target: b.id, kind: 'label-shared', projected: true,
          tags: [a.tag, b.tag], findingIds: [], caption: '',
          accessible: `Etiquetas que coinciden en un hallazgo: ${a.tag} y ${b.tag}`,
        });
        if (!edges.get(id).data.findingIds.includes(f.id)) edges.get(id).data.findingIds.push(f.id);
      }
    }
    const allNodes = [...nodes.values()], shownNodes = allNodes.filter(n => shown[n.data.kind]);
    return {
      visibility: shown, rootTag, expanded, nodes: shownNodes, edges: [...edges.values()],
      allNodes, baseEdges: [...baseEdges.values()], layoutRootId: labelId(rootTag),
      rootId: shown.label ? labelId(rootTag) : shownNodes.find(n => n.data.kind === 'finding')?.data.id || shownNodes[0]?.data.id || '',
      counts: Object.fromEntries(['note', 'finding', 'label'].map(kind => [kind, allNodes.filter(n => n.data.kind === kind).length])),
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
    { selector: 'edge[?projected]', style: { 'line-style': 'dashed', 'target-arrow-shape': 'none' } },
    { selector: 'edge[kind = "shared"], edge[kind = "note-shared"]', style: {
      'target-arrow-shape': 'none', 'line-style': 'dashed', 'line-color': '#ae9c6f',
      'curve-style': 'unbundled-bezier', 'control-point-distances': 35, 'control-point-weights': .5,
      label: 'data(caption)', 'font-size': 13, color: '#d8c793', 'text-wrap': 'wrap',
      'text-max-width': 115, 'text-background-color': '#152326',
      'text-background-opacity': 1, 'text-background-padding': 4,
      'text-background-shape': 'roundrectangle', 'text-margin-y': -12, 'text-rotation': 'autorotate',
    } },
    { selector: '.layer-hidden', style: { display: 'none' } },
    { selector: 'node.picked', style: { 'border-width': 1, 'border-color': '#b8d6ce', 'overlay-color': '#b8d6ce', 'overlay-padding': 7, 'overlay-opacity': .12, 'font-weight': 'bold', 'z-index': 5 } },
    { selector: 'edge.picked', style: { width: 2.8, 'line-color': '#b8d6ce', 'target-arrow-color': '#b8d6ce', opacity: 1, 'z-index': 4 } },
  ];
  function initialPositions(model) {
    const ids = model.allNodes.map(n => n.data.id), depth = new Map([[model.layoutRootId, 0]]), queue = [model.layoutRootId];
    while (queue.length) {
      const id = queue.shift();
      for (const {data:e} of model.baseEdges) {
        const next = e.source === id ? e.target : e.target === id ? e.source : null;
        if (next && !depth.has(next)) { depth.set(next, depth.get(id) + 1); queue.push(next); }
      }
    }
    const positions = { [model.layoutRootId]: { x: 0, y: 0 } };
    for (const level of [...new Set(ids.filter(id => id !== model.layoutRootId).map(id => depth.get(id) || 3))].sort()) {
      const ring = ids.filter(id => id !== model.layoutRootId && (depth.get(id) || 3) === level);
      ring.forEach((id, i) => {
        const angle = -Math.PI / 2 + i * Math.PI * 2 / ring.length + (level === 1 ? .23 : .66);
        positions[id] = { x: Math.cos(angle) * level * 155, y: Math.sin(angle) * level * 155 };
      });
    }
    return positions;
  }
  function mount(host, model, onSelect) {
    const positions = initialPositions(model);
    const combinedLayout = { name: 'cose', animate: false, randomize: false, fit: true, padding: 38, nodeDimensionsIncludeLabels: true, nodeRepulsion: () => 12000, idealEdgeLength: () => 65, nodeOverlap: 20, gravity: 1 };
    const cy = window.cytoscape({
      container: host, elements: [...model.allNodes.map(n => ({ ...n, classes: 'combined', position: positions[n.data.id] })), ...model.baseEdges],
      style: styles, layout: combinedLayout, minZoom: .15, maxZoom: 2.5,
      wheelSensitivity: .2, boxSelectionEnabled: false, autounselectify: true,
    });
    cy.getElementById(model.layoutRootId).addClass('root');
    function update(next, anchorId) {
      model = next;
      const shown = new Set(model.nodes.map(n => n.data.id));
      const anchor = cy.getElementById(anchorId || model.layoutRootId).position() || { x: 0, y: 0 };
      const occupied = cy.nodes().map(n => n.position());
      cy.batch(() => {
        for (const node of model.allNodes) if (!cy.getElementById(node.data.id).length) {
          let position;
          for (let attempt = 0; attempt < 200; attempt++) {
            const angle = attempt * 2.399963, radius = 130 + Math.floor(attempt / 12) * 80;
            position = { x: anchor.x + Math.cos(angle) * radius, y: anchor.y + Math.sin(angle) * radius };
            if (occupied.every(p => Math.hypot(p.x-position.x, p.y-position.y) > 115)) break;
          }
          occupied.push(position);
          cy.add({ ...node, classes: 'combined', position });
        }
        cy.nodes().forEach(n => n.toggleClass('layer-hidden', !shown.has(n.id())));
        cy.edges().remove();
        cy.add(model.edges);
      });
    }
    update(model);
    cy.on('tap', 'node, edge', event => onSelect(event.target.data()));
    let destroyed = false;
    let width = host.clientWidth, height = host.clientHeight;
    const observer = new ResizeObserver(() => {
      if (destroyed) return;
      const resized = host.clientWidth !== width || host.clientHeight !== height;
      width = host.clientWidth; height = host.clientHeight;
      cy.resize();
      if (resized) cy.fit(cy.elements(':visible'), 38);
    });
    observer.observe(host);
    const frame = requestAnimationFrame(() => { if (!destroyed) { cy.resize(); cy.fit(cy.elements(':visible'), 38); } });
    return {
      update,
      destroy() { destroyed = true; cancelAnimationFrame(frame); observer.disconnect(); cy.destroy(); },
      select(id) {
        cy.elements().removeClass('picked');
        const element = cy.getElementById(id);
        if (element.length && element.visible()) element.addClass('picked');
        else if (id.startsWith('finding:')) cy.edges().filter(e => e.data('findingIds')?.includes(id.slice(8))).addClass('picked');
      },
      zoom(factor) { const position = { x: cy.width() / 2, y: cy.height() / 2 }; cy.zoom({ level: Math.min(2.5, Math.max(.15, cy.zoom() * factor)), renderedPosition: position }); },
      fit() { cy.fit(cy.elements(':visible'), 38); },
      arrange() { cy.elements(':visible').layout(combinedLayout).run(); },
      exportPng() { return cy.png({ full: false, scale: 2, bg: '#152326' }); },
    };
  }
  window.LabGraph = { project, mount };
})();
