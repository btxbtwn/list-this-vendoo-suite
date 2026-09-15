// Runs in Vendoo's page world. Reuse the picker client so authentication stays
// inside Vendoo; only category records cross back to Studio.
async function readVendooCategoryChildren(marketplace, parentId) {
  try {
    if (!['general', 'ebay', 'poshmark', 'mercari', 'depop', 'etsy'].includes(marketplace)) {
      throw new Error('Unsupported category marketplace');
    }
    const entry = Array.from(document.scripts).find(script =>
      script.type === 'module' && /\/assets\/index-[^/]+\.js$/.test(new URL(script.src, location.href).pathname));
    if (!entry || new URL(entry.src).origin !== location.origin) throw new Error('Vendoo application module was not found');
    const cacheKey = '__studioCategoryClient';
    if (globalThis[cacheKey]?.url !== entry.src) {
      const response = await fetch(entry.src);
      if (!response.ok) throw new Error('Could not inspect Vendoo category client');
      const source = await response.text();
      const localName = source.match(/(?:var|const|let)\s+([\w$]+)=getCategories\.default=/)?.[1];
      const exports = source.slice(source.lastIndexOf('export{'));
      const escaped = String(localName || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const exportName = localName && exports.match(new RegExp('(?:[,{])' + escaped + ' as ([\\w$]+)(?:[,}])'))?.[1];
      if (!exportName) throw new Error('Vendoo category client changed; extraction needs an adapter update');
      const module = await import(entry.src);
      if (typeof module[exportName] !== 'function') throw new Error('Vendoo category client is unavailable');
      globalThis[cacheKey] = {url: entry.src, read: module[exportName]};
    }
    const nodes = await globalThis[cacheKey].read({
      marketplace_id: marketplace === 'general' ? 'vendoo' : marketplace,
      parent_category_id: parentId || '__root', text: '',
    });
    if (!Array.isArray(nodes)) throw new Error('Invalid category response');
    const normalized = nodes.map(node => {
      if (!node.id || !node.displayName || !Array.isArray(node.displayPath)
          || typeof node.hasChildren !== 'boolean' || typeof node.isLeaf !== 'boolean') {
        throw new Error('Incomplete category metadata returned by Vendoo');
      }
      return {id: String(node.id), label: node.displayName, path: node.displayPath,
        has_children: node.hasChildren, is_leaf: node.isLeaf};
    });
    return {ok: true, nodes: normalized, source: entry.src};
  } catch (error) {
    return {ok: false, error: error.message};
  }
}
