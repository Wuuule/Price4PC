'use strict';
const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL = value => { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : '#'; } catch { return '#'; } };
const yuan = value => value == null ? '—' : '¥' + Number(value).toLocaleString('zh-CN', {maximumFractionDigits:2});
const dateLabel = value => value ? new Date(value).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '尚未采集';
const names = {jd:'京东',taobao:'淘宝 / 天猫',pdd:'拼多多',smzdm:'好价报料',feed:'授权数据源'};
const statusNames = {ok:'有数据',blocked:'访问受限',login_required:'需登录',no_matches:'无匹配',error:'连接失败',not_run:'待采集'};
const kinds = {listed:'页面展示价',calculated:'确认优惠价',reported:'报料价 · 待验证'};
const colors = {jd:'#ee7459',taobao:'#6792e7',pdd:'#91bead'};
const icons = {CPU:'▦',GPU:'▤',RAM:'▥',SSD:'▣'};
let catalog = [], current = {offers:[],statuses:[],campaigns:[]}, history = [], category = 'all', days = 30;
let targets = {};
try { targets = JSON.parse(localStorage.getItem('price4pc-targets') || '{}'); } catch { /* Storage may be disabled. */ }

function currentOffers() {
  const now = Date.now();
  return (current.offers || []).filter(o => now-new Date(o.observed_at).getTime() >= 0 && now-new Date(o.observed_at).getTime() < 24*3600000 && (!o.coupon_expires_at || new Date(o.coupon_expires_at).getTime() > now));
}
function modeMatches(offer) {
  const mode = $('price-mode').value;
  return mode === 'reported' ? offer.price_kind === 'reported' : mode === 'calculated' ? offer.price_kind === 'calculated' : ['listed','calculated'].includes(offer.price_kind);
}
function offersFor(id, platform) {
  return currentOffers().filter(o => o.product_id === id && modeMatches(o) && (!platform || (o.price_kind === 'reported' ? o.merchant_platform === platform : o.platform === platform))).sort((a,b) => a.final_price-b.final_price);
}
function cell(o, best=false) {
  return o ? `<span class="price ${best ? 'best-price' : ''}"><small>¥</small>${Number(o.final_price).toLocaleString('zh-CN',{maximumFractionDigits:2})}</span>${best ? `<span class="best-platform">${escapeHTML(names[o.merchant_platform || o.platform] || '平台未确认')}</span>` : ''}` : '<span class="empty-price">暂无有效报价</span>';
}
function renderProducts() {
  const query = $('search').value.toLowerCase();
  const products = catalog.filter(p => (category==='all' || p.category===category) && (p.name+' '+p.query).toLowerCase().includes(query));
  $('products').innerHTML = products.map(p => {
    const best = offersFor(p.id)[0], target = targets[p.id];
    return `<tr data-product="${escapeHTML(p.id)}" tabindex="0" aria-label="查看 ${escapeHTML(p.name)} 的报价"><td><div class="product-name"><span class="product-icon ${p.category.toLowerCase()}">${icons[p.category]}</span><div><strong>${escapeHTML(p.name)}</strong><small>${p.category} · ${p.category==='RAM'?'不限品牌 / 台式机 / 单条':p.category==='SSD'?'不限品牌 / NVMe / M.2':p.category==='GPU'?'不限显卡品牌 / 具体型号需核对':'精确型号匹配 / 排除板 U 套装'}</small></div></div></td>${['jd','taobao','pdd'].map(platform => `<td>${cell(offersFor(p.id,platform)[0])}</td>`).join('')}<td>${cell(best,true)}</td><td><input class="target-input" type="number" min="1" max="100000" step="1" placeholder="目标价 ¥" data-target="${escapeHTML(p.id)}" value="${escapeHTML(target || '')}" aria-label="${escapeHTML(p.name)} 目标价格">${best && target && best.final_price<=target ? '<span class="target-hit">✓ 已达到目标价</span>' : ''}</td><td><button class="detail-button" aria-label="查看报价明细">↗</button></td></tr>`;
  }).join('') || '<tr class="loading-row"><td colspan="7">没有匹配的硬件</td></tr>';
  renderBudget();
}
function renderStats() {
  const offers = currentOffers();
  $('offer-count').textContent = offers.filter(o => o.price_kind!=='reported').length;
  $('discount-count').textContent = offers.filter(o => o.price_kind==='calculated').length;
  const ok = new Set((current.statuses || []).filter(s=>s.status==='ok' && ['jd','taobao','pdd'].includes(s.platform)).map(s=>s.platform));
  $('coverage-count').innerHTML = `${ok.size}<small>/ 3 个平台</small>`;
  $('coverage-label').textContent = ok.size ? [...ok].map(p=>names[p]).join(' · ') : '尚未获得有效平台报价';
  $('refresh-info').textContent = `最近采集 ${dateLabel(current.updated_at)}`;
  const last = new Date(current.updated_at).getTime();
  const allEmpty = offers.length === 0;
  $('notice').hidden = !allEmpty && !(Date.now()-last>24*3600000);
  if (allEmpty) $('notice').textContent = '当前没有可用的实时价格。下方可查看各平台采集状态；自动任务会继续尝试，历史记录仍然保留。';
  else if (Date.now()-last>24*3600000) $('notice').textContent = '最近采集已超过 24 小时，过期报价已从当前价格中移除。请查看 Actions 任务状态。';
}
function fillSelects() {
  const previous = $('chart-product').value;
  $('chart-product').innerHTML = catalog.map(p=>`<option value="${escapeHTML(p.id)}">${escapeHTML(p.name)}</option>`).join('');
  if (previous) $('chart-product').value = previous;
  if (!previous) $('chart-product').value = '9700x';
  for (const [id, cat] of [['build-cpu','CPU'],['build-gpu','GPU']]) {
    const old = $(id).value;
    $(id).innerHTML = catalog.filter(p=>p.category===cat).map(p=>`<option value="${escapeHTML(p.id)}">${escapeHTML(p.name)}</option>`).join('');
    if (old) $(id).value = old;
    else $(id).value = cat==='CPU' ? '9700x' : 'rx9070xt';
  }
}
function renderBudget() {
  const ids = [$('build-cpu').value,$('build-gpu').value,'ddr5-16gb','nvme-gen4-1tb'];
  const rows = ids.map(id=>offersFor(id)[0]);
  const missing = rows.filter(o=>!o).length;
  if ($('price-mode').value==='reported') {
    $('budget').textContent = '—'; $('budget-note').textContent = '第三方报料待验证，不参与预算合计';
  } else if (missing) {
    $('budget').textContent = '—'; $('budget-note').textContent = `还缺 ${missing} 项有效报价，暂不计算总价`;
  } else {
    $('budget').textContent = yuan(rows.reduce((sum,o)=>sum+o.final_price,0));
    $('budget-note').textContent = rows.every(o=>o.shipping!==null) ? '已含来源明确的运费；优惠条件请核对' : '页面价格合计；部分商品运费与结算条件待确认';
  }
}
function renderChart() {
  const id = $('chart-product').value, cutoff = Date.now()-days*86400000;
  const rows = history.filter(o=>o.product_id===id && modeMatches(o) && new Date(o.observed_at).getTime() >= cutoff && new Date(o.observed_at).getTime() <= Date.now());
  const aggregates = {};
  for (const row of rows) {
    const platform = row.price_kind==='reported' ? row.merchant_platform : row.platform;
    if (!colors[platform]) continue;
    const day = new Date(row.observed_at).toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'});
    const key = platform+day;
    if (!aggregates[key] || row.final_price<aggregates[key].price) aggregates[key] = {platform, day, price:row.final_price, time:new Date(day+'T12:00:00+08:00').getTime()};
  }
  const points = Object.values(aggregates);
  if (!points.length) {
    $('chart').innerHTML = '<div class="chart-empty"><span>↗</span><strong>每一个好价，都将留下轨迹</strong><p>尚无当前口径的历史记录，首次成功采集后自动开始绘制。</p></div>';
    $('history-summary').innerHTML = '<span>区间最低<strong>—</strong></span><span>区间最高<strong>—</strong></span><span>有效记录<strong>0</strong></span>';
    return;
  }
  const prices = points.map(p=>p.price), min = Math.min(...prices), max = Math.max(...prices);
  const padding = Math.max((max-min)*.18, min*.02, 1), lo = Math.max(0,min-padding), hi = max+padding;
  const times = points.map(p=>p.time), minTime = Math.min(...times), maxTime = Math.max(...times);
  const start = minTime===maxTime ? minTime-86400000 : minTime;
  const end = minTime===maxTime ? maxTime+86400000 : maxTime;
  const w=650,h=220,left=60,right=15,top=15,bottom=35;
  const x=t=>left+(t-start)/(end-start)*(w-left-right), y=p=>top+(hi-p)/(hi-lo)*(h-top-bottom);
  let svg=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="所选商品的每日采集最低价趋势">`;
  for(let i=0;i<4;i++) {
    const val=lo+(hi-lo)*i/3, pos=y(val);
    svg+=`<line x1="${left}" y1="${pos}" x2="${w-right}" y2="${pos}" stroke="#eef1f5"/><text x="${left-9}" y="${pos+3}" fill="#a0a9b6" font-size="9" text-anchor="end">${yuan(val)}</text>`;
  }
  for(let i=0;i<4;i++) {
    const t=start+(end-start)*i/3;
    svg+=`<text x="${x(t)}" y="${h-9}" fill="#a0a9b6" font-size="9" text-anchor="middle">${new Date(t).toLocaleDateString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit'})}</text>`;
  }
  for(const platform of Object.keys(colors)) {
    const series=points.filter(p=>p.platform===platform).sort((a,b)=>a.time-b.time);
    // Gaps remain gaps. An absent observation does not imply a stable price.
    let path='';
    series.forEach((p,i)=>{path+=`${i===0 || p.time-series[i-1].time>36*3600000?'M':'L'}${x(p.time).toFixed(2)},${y(p.price).toFixed(2)} `;});
    if(path) svg+=`<path d="${path}" fill="none" stroke="${colors[platform]}" stroke-width="2"/>`;
    for(const p of series) svg+=`<circle cx="${x(p.time)}" cy="${y(p.price)}" r="3.5" fill="${colors[platform]}" stroke="white" stroke-width="1.5"><title>${escapeHTML(names[platform])} ${p.day} ${yuan(p.price)}</title></circle>`;
  }
  $('chart').innerHTML=svg+'</svg>';
  $('history-summary').innerHTML=`<span>区间最低<strong>${yuan(min)}</strong></span><span>区间最高<strong>${yuan(max)}</strong></span><span>有效记录<strong>${rows.length}</strong></span>`;
}
function renderDeals() {
  const campaigns = current.campaigns || [], offers = currentOffers().filter(o=>o.price_kind==='reported').sort((a,b)=>a.final_price-b.final_price);
  const relevant = offers.filter(o=>/双.?11|双十一|11\.11/.test(o.title+' '+o.conditions));
  $('campaign-count').textContent = campaigns.length + relevant.length;
  $('deals').innerHTML = [...campaigns.map(c=>`<a class="deal" href="${escapeHTML(safeURL(c.source_url))}" target="_blank" rel="noopener noreferrer"><div><strong>${escapeHTML(c.title)}</strong><p>${escapeHTML(c.conditions || '')} · ${escapeHTML(names[c.platform] || '')} · ${dateLabel(c.starts_at)} — ${dateLabel(c.ends_at)}</p></div><span class="deal-price">↗<small>查看来源</small></span></a>`), ...offers.slice(0,12).map(o=>`<a class="deal" href="${escapeHTML(safeURL(o.url))}" target="_blank" rel="noopener noreferrer"><div><strong>${escapeHTML(o.title)}</strong><p>${escapeHTML(names[o.merchant_platform] || '平台未确认')} · ${escapeHTML(o.conditions)} · 抓取 ${dateLabel(o.observed_at)}${o.reported_date_text ? ' · 报料时间 '+escapeHTML(o.reported_date_text) : ''}</p></div><span class="deal-price">${yuan(o.final_price)}<small>报料价 · 待验证 ↗</small></span></a>`)].join('') || '<div class="empty-state">尚未采集到匹配的有效活动或报料。自动任务会持续搜索，不预填优惠规则。</div>';
}
function renderSources() {
  const statuses = current.statuses || [];
  $('source-summary').innerHTML = ['jd','taobao','pdd','smzdm'].map(platform=>{
    const rows=statuses.filter(s=>s.platform===platform), ok=rows.filter(s=>s.status==='ok').length;
    const allPending=!rows.length || rows.every(s=>s.status==='not_run');
    return `<div class="source-card"><div><strong>${names[platform]}</strong><span class="status-pill ${ok?'ok':allPending?'':'warn'}">${ok?'部分 / 全部成功':allPending?'等待首次采集':'未获得价格'}</span></div><p>${ok} / ${rows.length} 个查询成功 · ${rows.reduce((n,s)=>n+(s.count||0),0)} 条报价</p></div>`;
  }).join('');
  $('source-details').innerHTML=statuses.map(s=>`<tr><td>${escapeHTML(names[s.platform] || s.platform)}</td><td>${escapeHTML(catalog.find(p=>p.id===s.product_id)?.name || '数据接口')}</td><td><span class="status-pill ${s.status==='ok'?'ok':'warn'}">${escapeHTML(statusNames[s.status] || s.status)}</span></td><td>${escapeHTML(s.message)}</td><td>${dateLabel(s.checked_at)}</td></tr>`).join('');
}
function openProduct(id) {
  const product=catalog.find(p=>p.id===id);
  if(!product) return;
  $('chart-product').value=id; renderChart();
  $('dialog-title').textContent=product.name;
  const offers=offersFor(id);
  $('dialog-content').innerHTML=`<p>口径：${escapeHTML($('price-mode').selectedOptions[0].text)}。仅列出本次采集、24 小时内的有效观察。</p>`+(offers.length ? offers.map(o=>`<article class="offer-detail"><h3>${escapeHTML(o.title)}</h3><span class="price">${yuan(o.final_price)}</span><p>${escapeHTML(names[o.merchant_platform || o.platform] || '')} · ${escapeHTML(kinds[o.price_kind])} · ${dateLabel(o.observed_at)}</p><p>原价 ${yuan(o.base_price)} · 运费 ${o.shipping===null || o.shipping===undefined?'待确认':yuan(o.shipping)}</p><p>${escapeHTML(o.conditions)}</p>${o.applied_discounts?.length ? `<ul>${o.applied_discounts.map(d=>`<li>${escapeHTML(d.label)} −${yuan(d.saving)} <a href="${escapeHTML(safeURL(d.evidence_url))}" target="_blank" rel="noopener noreferrer">优惠依据 ↗</a></li>`).join('')}</ul>` : ''}${o.excluded_discounts?.length ? `<p>未计入优惠：${o.excluded_discounts.map(escapeHTML).join('、')}</p>` : ''}<a href="${escapeHTML(safeURL(o.url))}" target="_blank" rel="noopener noreferrer">查看商品 / 报料 ↗</a><a href="${escapeHTML(safeURL(o.source_url))}" target="_blank" rel="noopener noreferrer">价格来源 ↗</a></article>`).join('') : '<div class="empty-state">当前口径尚无该商品的有效报价，可查看下方采集状态。</div>')+'<p>目标价提醒保存在当前浏览器，只在打开或刷新页面时检查，不会发送后台通知。</p>';
  $('offer-dialog').showModal();
}
async function loadData() {
  $('refresh').disabled=true;
  try {
    const results=await Promise.all(['catalog','current','history'].map(async name=>{
      const response=await fetch(`./data/${name}.json?t=${Date.now()}`,{cache:'no-store'});
      if(!response.ok) throw new Error(`${name}: HTTP ${response.status}`);
      return response.json();
    }));
    if(!Array.isArray(results[0]) || !Array.isArray(results[2]) || !Array.isArray(results[1].offers)) throw new Error('数据格式不正确');
    [catalog,current,history]=results;
    fillSelects(); renderStats(); renderProducts(); renderChart(); renderDeals(); renderSources();
  } catch(error) {
    $('notice').hidden=false;
    $('notice').textContent='价格数据加载失败。请刷新页面，或查看 GitHub Actions 的发布状态。';
    $('refresh-info').textContent='加载失败';
    if(!catalog.length) $('products').innerHTML='<tr class="loading-row"><td colspan="7">价格数据暂时不可用</td></tr>';
    console.error(error);
  } finally { $('refresh').disabled=false; }
}
$('refresh').addEventListener('click',loadData);
$('search').addEventListener('input',renderProducts);
$('price-mode').addEventListener('change',()=>{renderProducts();renderChart();});
$('categories').addEventListener('click',event=>{
  const button=event.target.closest('[data-category]'); if(!button) return;
  category=button.dataset.category;
  document.querySelectorAll('[data-category]').forEach(b=>b.classList.toggle('selected',b===button));
  renderProducts();
});
$('products').addEventListener('click',event=>{
  if(event.target.closest('input')) return;
  const row=event.target.closest('[data-product]'); if(row) openProduct(row.dataset.product);
});
$('products').addEventListener('keydown',event=>{if(event.key==='Enter' && !event.target.closest('input')) { const row=event.target.closest('[data-product]'); if(row) openProduct(row.dataset.product); }});
$('products').addEventListener('change',event=>{
  const input=event.target.closest('[data-target]'); if(!input) return;
  const number=Number(input.value);
  if(number>0 && number<=100000) targets[input.dataset.target]=number; else delete targets[input.dataset.target];
  try { localStorage.setItem('price4pc-targets',JSON.stringify(targets)); } catch { /* In-memory reminders still work. */ }
  renderProducts();
});
$('chart-product').addEventListener('change',renderChart);
for(const id of ['build-cpu','build-gpu']) $(id).addEventListener('change',renderBudget);
document.querySelector('.range-tabs').addEventListener('click',event=>{const button=event.target.closest('[data-days]');if(!button)return;days=Number(button.dataset.days);document.querySelectorAll('[data-days]').forEach(b=>b.classList.toggle('selected',b===button));renderChart();});
$('close-dialog').addEventListener('click',()=>$('offer-dialog').close());
$('offer-dialog').addEventListener('click',event=>{if(event.target===$('offer-dialog')) { const r=event.target.getBoundingClientRect();if(event.clientX<r.left || event.clientX>r.right || event.clientY<r.top || event.clientY>r.bottom)event.target.close(); }});
$('export').addEventListener('click',()=>{
  const fields=['product_id','platform','price_kind','final_price','base_price','observed_at','title','url'];
  const quote=value=>{let s=String(value ?? '');if(/^[=+@\-\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};
  const csv='\uFEFF'+[fields.join(','),...history.map(row=>fields.map(key=>quote(row[key])).join(','))].join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=`Price4PC-history-${new Date().toISOString().slice(0,10)}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
const observer=new IntersectionObserver(entries=>{for(const entry of entries){if(entry.isIntersecting)document.querySelectorAll('.nav-link').forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+entry.target.id));}},{rootMargin:'-10% 0px -70% 0px'});
for(const id of ['overview','history','campaign','sources'])observer.observe($(id));
loadData();
