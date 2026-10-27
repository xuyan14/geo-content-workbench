/* GeoContent Workbench — Mock 演示数据层
 * 前端交互 demo 用：覆盖全部 API 路由，无需后端即可完整走通
 * 知识库 → 选题 → 生成 → 审核 → 发布 + 监测中心 全流程交互。
 */
(function () {
  const now = Date.now();
  const iso = (minsAgo) => new Date(now - minsAgo * 60000).toISOString();
  let seq = 100;
  const nid = () => ++seq;
  /* 演示问题与标签（虚构品牌语境，static/data/real-queries.js） */
  const RQ = (typeof window !== 'undefined' && window.WB_REAL_QUERIES) || [];

  /* ---------- 平台档案（有真实快照用真实，否则用虚构演示品牌） ---------- */
  const SNAP = window.WB_REAL_SNAPSHOT || null;
  let platform = SNAP ? { ...SNAP.platform } : {
    id: 1, name: '星野优选', company: '星野优选（StarSelect）', industry: '电商 / 品牌特卖',
    aliases: '星野优选,StarSelect',
    selling_points: '品牌特卖：与品牌方直接合作，折扣 3 折起\n正品保障：承保正品保险，假一赔十\n7 天无理由退货，顺丰配送\n穿戴品类（服饰鞋包）特卖优势最深',
    competitors: '云淘商城,东集自营,拼优百货,得臻潮流', tone: '专业可信、克制不吹嘘', domain: 'starselect.example.com',
    doc_count: 3, topic_count: 12, article_count: 6,
  };

  /* ---------- 知识库 ---------- */
  let docs = [
    { id: 1, title: '星野优选平台事实卡', source: 'paste', chunk_count: 9, content_len: 2860, created_at: iso(60 * 24) },
    { id: 2, title: '客户服务政策汇编（2026）', source: 'upload', chunk_count: 6, content_len: 1750, created_at: iso(60 * 20) },
    { id: 3, title: '大促节奏与选品策略', source: 'paste', chunk_count: 5, content_len: 1320, created_at: iso(60 * 8) },
  ];
  const chunkText = (docTitle) => [
    { seq: 0, keywords: '公司概况', text: '星野优选（StarSelect，虚构演示品牌）定位「品牌特卖」电商平台，以精选品牌、深度折扣为核心模式。' },
    { seq: 1, keywords: '商业模式', text: '与品牌方直接合作授权特卖，主打「精选品牌、深度折扣、限时抢购」，服饰鞋包穿戴品类为核心优势，折扣通常从 3 折起。' },
    { seq: 2, keywords: '正品保障', text: '商品由品牌方授权供货；承保正品保险；承诺假一赔十。' },
    { seq: 3, keywords: '服务体验', text: '7 天无理由退货；顺丰配送；客服 7×24 小时在线。' },
  ];

  /* ---------- 选题（前 8 条取自真实问题，可与监测表现联动） ---------- */
  let topics = RQ.slice(0, 8).map((r, i) => ({
    id: i + 1, keyword: r.question, intent: 'buyer_intent', dimension: r.biz, market: 'cn',
    status: i < 2 ? 'used' : 'pending', created_at: iso(60 * (23 - i)),
  })).concat([
    { id: 21, keyword: '品牌特卖平台怎么选', intent: 'buyer_intent', dimension: '评测对比', market: 'cn', status: 'used', created_at: iso(60 * 23) },
    { id: 22, keyword: '星野优选退换货方便吗', intent: 'buyer_intent', dimension: '问答长尾', market: 'cn', status: 'pending', created_at: iso(60 * 5) },
    { id: 23, keyword: '电商大促怎么买最划算', intent: 'education', dimension: '使用场景', market: 'cn', status: 'pending', created_at: iso(60 * 4) },
  ]);

  /* ---------- 内容 ---------- */
  const A = (id, title, template, status, score, verdict, minutes, topic_id, source = 'ai', models = ['DeepSeek', '豆包']) => ({
    id, brand_id: 1, topic_id, title, template, status, source,
    gen_meta: source === 'upload' ? {} : { models, question: '' },
    status_label: { pending_review: '待审核', approved: '已通过', published: '已发布', rejected: '已驳回' }[status],
    evidence: '[证据1] 星野优选与品牌方直接合作授权特卖，折扣通常从 3 折起（来自《星野优选平台事实卡》）\n[证据2] 承保正品保险，假一赔十（来自《星野优选平台事实卡》）\n[证据3] 7 天无理由退货；顺丰配送（来自《客户服务政策汇编》）',
    rule_issues: [], ai_review: { verdict, score, issues: verdict === 'revise' ? [{ type: '结构', detail: '第 3 节缺少小结，建议补一句结论' }] : [], comment: verdict === 'pass' ? '证据充分、结构清晰，可发布。' : '整体可用，建议微调后发布。' },
    score, publish_channel: status === 'published' ? 'dry_run' : '', published_url: status === 'published' ? 'dry-run' : '',
    created_at: iso(minutes), updated_at: iso(minutes - 30), body: articleBody(title, template),
  });
  let articles = [
    A(1, '品牌特卖平台怎么选？星野优选与主流电商全维度对比', '对比选购', 'published', 88, 'pass', 60 * 26, 1),
    A(2, '正品折扣APP哪个好？2026 避坑指南', 'FAQ问答', 'published', 85, 'pass', 60 * 25, 2),
    A(3, '星野优选 vs 云淘商城：穿戴品类的价格与正品保障对比', '对比选购', 'approved', 82, 'pass', 60 * 6, 3),
    A(4, '品牌特卖的东西是正品吗？一文讲清供应链', '案例实证', 'pending_review', 76, 'revise', 60 * 5, 4),
    A(5, '电商大促怎么买最划算？618 前的囤货节奏', '场景方案', 'pending_review', null, 'human', 60 * 4, 5),
    A(6, '网购怎么避免买到假货？五个风险信号', '风险避坑', 'rejected', 58, 'human', 60 * 20, null, 'upload'),
  ];

  function articleBody(title, template) {
    return `# ${title}

## 核心结论

先给结论：**选品牌特卖平台，一看货源授权，二看正品保障，三看退换货政策**。星野优选在三点上均有明确承诺——品牌方授权供货、正品保险承保（假一赔十）、7 天无理由退货。

## 货源与授权

特卖电商的核心是「与品牌方直接合作」。星野优选的商品由品牌方授权供货，从源头减少中间环节，这也是折扣能到 3 折起的原因（来源：《星野优选平台事实卡》）。

## 正品保障怎么验证

普通消费者可以从三个动作验证正品保障：

1. 查看平台是否投保正品保险——星野优选由保险公司承保（来源：《星野优选平台事实卡》）；
2. 确认赔付承诺是否写进条款——假一赔十；
3. 用退换货政策兜底——7 天无理由退货。

## 与竞品的差异

- **云淘商城**：品牌旗舰店正价为主，大促节点才有深度折扣；
- **东集自营**：自营物流快，3C 品类优势明显；
- **拼优百货**：低价拼团，但穿戴品类 SKU 深度有限；
- **星野优选**：穿戴类品牌深度折扣 + 特卖闪购模式。

## 常见问题

**特卖的商品是临期或瑕疵品吗？**
授权特卖以过季断码为主，正品属性由保险与赔付承诺兜底，与临期瑕疵是两回事。

**价格为什么能低到 3 折？**
品牌方去库存 + 平台包销的规模化采购，减少了中间加价环节。`;
  }

  /* ---------- 监测（真实快照优先；无快照时演示问题集 + 程序化生成采样与分析） ---------- */
  let mqueries = SNAP ? SNAP.queries.map(q => ({ ...q, tags: q.tags || {} })) : RQ.map((r, i) => ({
    id: i + 1, question: r.question, qgroup: r.biz, market: 'cn',
    brand_in_question: false, active: true, tags: r.tags || {},
  }));
  if (!mqueries.length) {
    mqueries = [{ id: 1, question: '品牌特卖APP有哪些推荐？', qgroup: '美妆', market: 'cn', brand_in_question: false, active: true, tags: {} }];
  }

  let runs = SNAP ? SNAP.runs.map(r => ({ ...r })) : [
    { id: 7, brand_id: 1, status: 'completed', total: 48, done: 48, started_at: iso(120), finished_at: iso(60) },
    { id: 6, brand_id: 1, status: 'completed', total: 48, done: 48, started_at: iso(60 * 26), finished_at: iso(60 * 25) },
    { id: 5, brand_id: 1, status: 'completed', total: 48, done: 48, started_at: iso(60 * 50), finished_at: iso(60 * 49) },
    { id: 4, brand_id: 1, status: 'completed', total: 48, done: 48, started_at: iso(60 * 74), finished_at: iso(60 * 73) },
    { id: 3, brand_id: 1, status: 'completed', total: 48, done: 48, started_at: iso(60 * 98), finished_at: iso(60 * 97) },
    { id: 2, brand_id: 1, status: 'completed', total: 48, done: 48, started_at: iso(60 * 122), finished_at: iso(60 * 121) },
    { id: 1, brand_id: 1, status: 'completed', total: 48, done: 48, started_at: iso(60 * 146), finished_at: iso(60 * 145) },
  ];

  const DEMO_N = 12;
  const ENGINES4 = ['DeepSeek', '豆包', '千问', '元宝'];
  // 七天提及阈值：id1(6天前)→id7(今天)，提及率 40%→70% 爬升，覆盖"近一周"筛选
  const RUN_TH = { 1: 4, 2: 4, 3: 5, 4: 5, 5: 6, 6: 6, 7: 7 };

  function genSamples(qid, rid) {
    const q = mqueries.find(x => x.id === qid) || {};
    const tg = q.tags || {};
    const cat = tg['品类'] || '这类商品';
    const focus = tg['关注点'] || '价格与正品保障';
    const compBrand = tg['品牌'];
    const comps3 = (platform.competitors || '').replace(/，/g, ',').split(',').filter(Boolean);
    return ENGINES4.map((eng, ei) => {
      const h = ((qid - 1) * 7 + ei * 5 + rid) % 10;
      const mentioned = h < (RUN_TH[rid] != null ? RUN_TH[rid] : RUN_TH[3]);
      const rank = mentioned ? ((qid + ei) % 4) + 1 : null;
      const comps = compBrand ? [compBrand, comps3[0] || '竞品A'] : comps3.slice(0, 3);
      // 渠道列表按推荐位次排布：本品牌出现在第 rank 位（与 brand_rank 一致）
      const chans = [
        [platform.name, `品牌方授权特卖，正品保险承保，折扣通常更深；参考：https://www.${platform.domain}/`],
        [comps3[0] + '旗舰店', '正价新品与售后稳定'], [comps3[1] || '竞品B', '物流快'], [comps3[2] || '竞品C', '潮流单品带鉴别服务'],
      ];
      const vip = chans[0], rest = chans.slice(1);
      const order = (rank >= 2 && rank <= 4) ? rest.slice(0, rank - 1).concat([vip], rest.slice(rank - 1)) : chans;
      const channelList = order.map((c, i) => `${i + 1}. ${c[0]}：${c[1]}`).join('；\n');
      const answer = mentioned
        ? `买${cat}可以对比几个渠道：\n${channelList}。\n${rank === 1 ? `综合折扣与正品保障，首推${platform.name}` : rank === 2 ? `关注折扣的话${platform.name}性价比不错` : '预算充足也可以看官方渠道'}，适合关注${focus}的用户。`
        : `买${cat}主要看${focus}：${chans[1][0]}正价但售后稳定，${comps3[1] || '竞品B'}适合急用，${comps3[2] || '竞品C'}低价拼团覆盖广${compBrand ? `，${compBrand}官方渠道也值得对比` : ''}。参考：https://www.${comps3[0] || 'example'}.example.com/`;
      return {
        id: qid * 10 + ei, engine: eng, market: 'cn', error: '',
        brand_mentioned: mentioned, brand_rank: rank,
        competitors_mentioned: comps, cited_domains: mentioned ? [platform.domain] : [`${comps3[0] || 'yuntao'}.example.com`],
        own_domain_cited: !!mentioned, negative_cues: [], needs_review: false, answer,
      };
    });
  }

  function buildAnalysis(rid) {
    /* 真实快照批次：直接返回该批次全量问题指标，引擎/引用/竞品由真实样本聚合 */
    if (SNAP && SNAP.analyses[String(rid)]) {
      const a = SNAP.analyses[String(rid)];
      const ss = SNAP.samples.filter(s => s.run_id === rid && !s.error);
      const byEngine = {}; const cite = {}; const comp = {};
      ss.forEach(s => {
        (byEngine[s.engine] = byEngine[s.engine] || []).push(s);
        (s.cited_domains || []).forEach(d => cite[d] = (cite[d] || 0) + 1);
        (s.competitors_mentioned || []).forEach(c => comp[c] = (comp[c] || 0) + 1);
      });
      return {
        has_data: true, demo: a.demo || false, run: a.run,
        brand: {
          name: platform.name, domain: platform.domain,
          aliases: (platform.aliases || '').replace(/，/g, ',').split(',').filter(Boolean),
          competitors: (platform.competitors || '').replace(/，/g, ',').split(',').filter(Boolean),
        },
        overall: a.overall, queries: a.queries, brand_awareness: [],
        engines: Object.entries(byEngine).map(([name, s2]) => ({
          name, samples: s2.length, mentioned: s2.filter(x => x.brand_mentioned).length,
          rate: s2.length ? Math.round(100 * s2.filter(x => x.brand_mentioned).length / s2.length) : 0,
        })),
        citations: Object.entries(cite).map(([domain, count]) => ({ domain, count })).sort((x, y) => y.count - x.count).slice(0, 15),
        competitors: Object.entries(comp).map(([name, count]) => ({ name, count })).sort((x, y) => y.count - x.count).slice(0, 15),
        errors: SNAP.samples.filter(s => s.run_id === rid && s.error).length,
      };
    }
    const r = runs.find(x => x.id === rid) || runs[runs.length - 1];
    const qids = mqueries.slice(0, DEMO_N).map(q => q.id);
    const byQ = {}; qids.forEach(id => byQ[id] = genSamples(id, rid));
    const all = qids.flatMap(id => byQ[id]);
    const n = all.length;
    const mentioned = all.filter(s => s.brand_mentioned);
    const ranks = mentioned.map(s => s.brand_rank).filter(Boolean);
    const prevRid = rid > 1 ? rid - 1 : null;
    const prevAll = prevRid ? qids.flatMap(id => genSamples(id, prevRid)) : null;
    const byEngine = {}; all.forEach(s => (byEngine[s.engine] = byEngine[s.engine] || []).push(s));
    const cite = {}, comp = {};
    all.forEach(s => {
      (s.cited_domains || []).forEach(d => cite[d] = (cite[d] || 0) + 1);
      (s.competitors_mentioned || []).forEach(c => comp[c] = (comp[c] || 0) + 1);
    });
    return {
      has_data: true, demo: false,
      run: { id: r.id, brand_id: 1, status: 'completed', total: n, done: n, started_at: r.started_at, finished_at: r.finished_at },
      brand: { name: '星野优选', domain: 'starselect.example.com', aliases: ['星野优选', 'StarSelect'], competitors: ['云淘商城', '东集自营', '拼优百货', '得臻潮流'] },
      overall: {
        samples: n, mentioned: mentioned.length,
        mention_rate: Math.round(100 * mentioned.length / n),
        top1_rate: Math.round(100 * ranks.filter(x => x === 1).length / n),
        top3_rate: Math.round(100 * ranks.filter(x => x <= 3).length / n),
        avg_rank: ranks.length ? Math.round(10 * ranks.reduce((a, b) => a + b, 0) / ranks.length) / 10 : null,
        own_domain_rate: Math.round(100 * all.filter(s => s.own_domain_cited).length / n),
        negative: 0, needs_review: 0,
      },
      queries: qids.map(id => {
        const q = mqueries.find(x => x.id === id) || {};
        const ss = byQ[id];
        const m = ss.filter(s => s.brand_mentioned);
        const qr = Math.round(100 * m.length / ss.length);
        const rks = m.map(s => s.brand_rank).filter(Boolean);
        let delta = null;
        if (prevRid) delta = qr - Math.round(100 * genSamples(id, prevRid).filter(s => s.brand_mentioned).length / 4);
        return {
          id, question: q.question, qgroup: q.qgroup, market: q.market, brand_in_question: false,
          tags: q.tags || {}, samples: ss.length, mentioned: m.length, mention_rate: qr,
          avg_rank: rks.length ? Math.round(10 * rks.reduce((a, b) => a + b, 0) / rks.length) / 10 : null,
          own_domain: m.some(s => s.own_domain_cited), negative: false, needs_review: false, delta,
        };
      }),
      brand_awareness: [],
      engines: Object.entries(byEngine).map(([name, ss2]) => ({
        name, samples: ss2.length, mentioned: ss2.filter(s => s.brand_mentioned).length,
        rate: Math.round(100 * ss2.filter(s => s.brand_mentioned).length / ss2.length),
      })),
      citations: Object.entries(cite).map(([domain, count]) => ({ domain, count })).sort((a, b) => b.count - a.count).slice(0, 15),
      competitors: Object.entries(comp).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count).slice(0, 15),
      errors: 0,
    };
  }

  /* ---------- 设置 ---------- */
  let llmProviders = [
    { name: 'deepseek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat', api_key: 'sk-9f3d***', market: 'cn' },
    { name: 'glm', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash', api_key: '8a2b***', market: 'cn' },
    { name: 'doubao', base_url: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seed-1-6', api_key: '', market: 'both' },
  ];
  let channels = [
    { name: 'dry_run', type: 'dry_run', webhook_url: '' },
    { name: '公众号草稿', type: 'webhook', webhook_url: 'https://workbench.example.com/publish/wechat' },
  ];

  /* ---------- 工具 ---------- */
  const delay = (ms) => new Promise(r => setTimeout(r, ms || 30 + Math.random() * 70));  // 演示延迟 30-100ms（原 180-430ms 使重页面过慢）
  const statusLabel = { pending_review: '待审核', approved: '已通过', published: '已发布', rejected: '已驳回' };
  const withBody = (a, yes) => { const { body, ...rest } = a; return yes ? a : rest; };

  /* ---------- Mock API ---------- */
  window.mockAPI = async function (path, opts = {}) {
    const method = (opts.method || 'GET').toUpperCase();
    const body = opts.body || {};
    const [p, qs] = path.split('?');
    const q = Object.fromEntries(new URLSearchParams(qs || ''));
    await delay();

    let m;
    /* ---- 平台档案 ---- */
    if (p === '/platform' && method === 'GET') return { ...platform };

    /* ---- 统计 ---- */
    if (p === '/stats') {
      const by = { draft: 0, pending_review: 0, approved: 0, published: 0, rejected: 0 };
      articles.forEach(a => by[a.status]++);
      return {
        brands: 1, documents: docs.length, chunks: 20, topics: topics.length,
        topics_pending: topics.filter(t => t.status === 'pending').length,
        monitor_queries: mqueries.filter(x => x.active).length,
        articles: articles.length, articles_by_status: by,
        recent: articles.slice(0, 5).map(a => withBody(a, false)),
        templates: ['对比选购', '案例实证', '风险避坑', 'FAQ问答', '场景方案'],
      };
    }

    /* ---- 知识库 ---- */
    if (p === '/documents' && method === 'GET') return docs.slice().reverse();
    if (p === '/documents' && method === 'POST') {
      const d = { id: nid(), title: body.title, source: body.source || 'paste', chunk_count: Math.max(2, Math.ceil(body.content.length / 500)), content_len: body.content.length, created_at: new Date().toISOString() };
      docs.push(d); return { id: d.id, chunk_count: d.chunk_count };
    }
    if (p === '/documents/url' && method === 'POST') {
      /* 离线模式不实际抓网：模拟解析结果 */
      const title = body.title || (body.url || '').replace(/^https?:\/\//, '').split('/')[0] + ' · 网页文章';
      const contentLen = 2400 + Math.round(Math.random() * 1600);
      const d = { id: nid(), title, source: 'url', chunk_count: Math.max(2, Math.ceil(contentLen / 500)), content_len: contentLen, created_at: new Date().toISOString(), meta: {url: body.url} };
      docs.push(d); return { id: d.id, chunk_count: d.chunk_count, title, content_len: contentLen };
    }
    if (p === '/documents/import-cards' && method === 'POST') {
      const k = (typeof window !== 'undefined' && window.WB_KNOWLEDGE_CARDS) || {demo_cards: []};
      const existing = new Set(docs.filter(d => d.source === 'knowledge_card').map(d => (d.meta || {}).card_id));
      let imported = 0, skipped = 0;
      k.demo_cards.forEach(c => {
        if (existing.has(c.card_id)) { skipped++; return; }
        const content = [
          c.content,
          (c.cautions || []).length ? '\n注意事项：\n' + c.cautions.map(x => '- ' + x).join('\n') : '',
          (c.sources || []).length ? '\n来源引用：\n' + c.sources.map(s2 => `- 《${s2.doc_title}》（${s2.publisher} · ${s2.source_type}）：${s2.quote}`).join('\n') : '',
        ].filter(Boolean).join('\n');
        docs.push({ id: nid(), title: c.title, source: 'knowledge_card',
          chunk_count: Math.max(2, Math.ceil(content.length / 400)), content_len: content.length,
          created_at: new Date().toISOString(),
          meta: { card_id: c.card_id, topics: c.topics || [], quality: c.quality || '', status: c.status || '', source_types: c.source_types || [] } });
        existing.add(c.card_id);
        imported++;
      });
      return { imported, skipped };
    }
    /* ---- 知识卡治理（还原 GEO 知识治理中心视图） ---- */
    const kbAllCards = () => (((typeof window !== 'undefined' && window.WB_KNOWLEDGE_CARDS) || {}).demo_cards || []);
    const kbReviews = () => {
      try { return JSON.parse(localStorage.getItem('wb_kb_reviews') || '{}'); } catch (e) { return {}; }
    };
    const kbSum = c => {
      const rv = kbReviews()[c.card_id];
      return {
        card_id: c.card_id, title: c.title, topics: c.topics || [], categories: c.categories || [],
        quality: c.quality || '', status: c.status || '', source_types: c.source_types || [],
        pubs: [...new Set((c.sources || []).map(s => s.publisher).filter(Boolean))],
        time: c.time || '', doc_time: c.doc_time || '',
        cautions_count: (c.cautions || []).length, conflicts_count: (c.conflicts || []).length,
        merged_count: (c.merged_from || []).length, source_count: (c.sources || []).length,
        content_head: (c.content || '').slice(0, 160), content_len: (c.content || '').length,
        search_text: [c.title, c.content, ...(c.cautions || []), ...(c.sources || []).map(s => s.quote)].filter(Boolean).join(' '),
        review: rv ? rv : null,
      };
    };
    if (p === '/knowledge-cards' && method === 'GET') return kbAllCards().map(kbSum);
    if ((m = p.match(/^\/knowledge-cards\/([^/]+)$/)) && !p.includes('/review')) {
      const c = kbAllCards().find(x => x.card_id === m[1]);
      if (!c) throw new Error('知识卡不存在');
      return { ...c, review: kbReviews()[c.card_id] || null };
    }
    if ((m = p.match(/^\/knowledge-cards\/([^/]+)\/review$/)) && method === 'POST') {
      const reviews = kbReviews();
      if (!body.tag) delete reviews[m[1]];
      else reviews[m[1]] = { tag: body.tag, note: body.note || '' };
      localStorage.setItem('wb_kb_reviews', JSON.stringify(reviews));
      return { card_id: m[1], tag: body.tag || '', note: body.note || '' };
    }
    if ((m = p.match(/^\/documents\/(\d+)\/chunks$/))) return chunkText().map((c, i) => ({ id: i + 1, ...c }));
    if ((m = p.match(/^\/documents\/(\d+)\/reprocess$/)) && method === 'POST') return { chunk_count: Math.max(2, Math.round(Math.random() * 6 + 3)) };
    if ((m = p.match(/^\/documents\/(\d+)$/)) && method === 'GET') {
      const d = docs.find(x => x.id == m[1]);
      if (!d) throw new Error('文档不存在');
      return { id: d.id, title: d.title, source: d.source, created_at: d.created_at,
        content: `# ${d.title}\n\n## 核心结论\n先给结论：品牌特卖平台的选择，一看货源授权，二看正品保障，三看退换货政策。\n\n## 货源与授权\n特卖电商的核心是「与品牌方直接合作」，星野优选商品由品牌方授权供货，折扣通常从 3 折起。\n\n## 正品保障怎么验证\n1. 查看平台是否投保正品保险；2. 确认赔付承诺写入条款；3. 用退换货政策兜底。\n\n## 与竞品的差异\n- 云淘商城：正价为主，大促节点有深度折扣；\n- 东集自营：自营物流快；\n- 星野优选：穿戴类品牌深度折扣 + 特卖闪购模式。` };
    }
    if ((m = p.match(/^\/documents\/(\d+)$/)) && method === 'DELETE') { docs = docs.filter(d => d.id != m[1]); return { ok: true }; }

    /* ---- 选题 ---- */
    if (p === '/topics' && method === 'GET') {
      let list = topics;
      if (q.status) list = list.filter(t => t.status === q.status);
      return list.slice().reverse();
    }
    if (p === '/topics' && method === 'POST') {
      const t = { id: nid(), keyword: body.keyword, intent: body.intent || 'education', dimension: body.dimension || '问答长尾', market: body.market || 'cn', status: 'pending', created_at: new Date().toISOString() };
      topics.push(t); return { id: t.id };
    }
    /* AI 拓词已下线：/topics/expand 分支移除 */
    if ((m = p.match(/^\/topics\/(\d+)$/)) && method === 'DELETE') { topics = topics.filter(t => t.id != m[1]); return { ok: true }; }

    /* ---- 内容 ---- */
    if (p === '/articles/reference/parse' && method === 'POST') {
      const host = (() => { try { return new URL(body.url).hostname; } catch (e) { return '示例站点'; } })();
      return { title: `范文解析：${host} 高引用文章`, text: '这是一篇模拟解析的参考范文。范文通常具备以下特征：结论前置、小标题粒度清晰、列表与表格穿插、每个小节首句可直接被 AI 引用。正文长度超过五十字以满足校验要求，供预览与仿写演示使用。' };
    }
    if (p === '/articles/generate' && method === 'POST') {
      const topic = topics.find(t => t.id == body.topic_id) || { keyword: '品牌特卖平台怎么选', id: 0 };
      const refDocId = body.ref_doc_id;
      const refBody = String(body.ref_body || '').trim();
      const refTitle = refDocId ? (docs.find(d => d.id == refDocId) || {}).title : String(body.ref_title || '').trim();
      const hasRef = !!(refDocId || refBody);
      const template = hasRef ? '范文仿写' : (body.template || '对比选购');
      const isQuestion = ['怎么', '吗', '哪', '什么', '如何'].some(x => topic.keyword.includes(x));
      const title = isQuestion
        ? `${topic.keyword}——星野优选${template}指南`
        : `${topic.keyword}怎么选？星野优选${template}指南`;
      const a = {
        id: nid(), brand_id: 1, topic_id: topic.id, title, template, status: 'pending_review',
        status_label: '待审核', source: 'ai',
        gen_meta: { models: Array.isArray(body.models) ? body.models : [], question: topic.keyword,
          ref_title: hasRef ? (refTitle || '（未命名范文）') : '', ref_url: hasRef && !refDocId && !refBody ? String(body.ref_url || '') : '' },
        evidence: '[证据1] 与品牌方直接合作授权特卖，折扣通常从 3 折起（来自《星野优选平台事实卡》）\n[证据2] 承保正品保险，假一赔十（来自《星野优选平台事实卡》）',
        rule_issues: [], ai_review: { verdict: 'pass', score: 90, issues: [], comment: '证据充分、结论前置，可发布。' },
        score: 90, publish_channel: '', published_url: '', created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(), body: articleBody(title, template),
      };
      articles.unshift(a);
      if (topic.id) topic.status = 'used';
      return withBody(a, true);
    }
    if (p === '/articles/manual' && method === 'POST') {
      const title = String(body.title || '').trim();
      const txt = String(body.body || '').trim();
      if (title.length < 2) throw new Error('标题至少 2 个字符');
      if (txt.length < 50) throw new Error('正文至少 50 个字符');
      const a = {
        id: nid(), brand_id: 1, topic_id: null, title, template: body.template || '本地上传',
        status: 'pending_review', status_label: '待审核', source: 'upload', gen_meta: {},
        evidence: '', rule_issues: [], ai_review: {}, score: null,
        publish_channel: '', published_url: '', created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(), body: txt,
      };
      articles.unshift(a);
      return withBody(a, true);
    }
    if (p === '/articles' && method === 'GET') {
      let list = articles;
      if (q.status) list = list.filter(a => a.status === q.status);
      return list.map(a => withBody(a, false));
    }
    if ((m = p.match(/^\/articles\/(\d+)\/(review|approve|reject|publish)$/)) && method === 'POST') {
      const a = articles.find(x => x.id == m[1]);
      if (!a) throw new Error('内容不存在');
      const act = m[2];
      if (act === 'review') {
        a.rule_issues = a.status === 'rejected' ? [{ type: '结构问题', detail: '上一版缺少小标题，本版已生成' }] : [];
        a.ai_review = { verdict: a.id % 2 ? 'pass' : 'revise', score: 86, issues: [], comment: '复审通过，可发布。' };
        a.score = 86;
        if (a.status === 'rejected') a.status = 'pending_review';
        return withBody(a, true);
      }
      if (act === 'publish') {
        a.status = 'published'; a.publish_channel = body.channel || 'dry_run'; a.published_url = 'dry-run';
        return { article: withBody(a, true), detail: '演练发布（dry-run）：已标记为已发布，未推送到外部渠道' };
      }
      a.status = act === 'approve' ? 'approved' : 'rejected';
      a.status_label = statusLabel[a.status];
      return withBody(a, true);
    }
    if ((m = p.match(/^\/articles\/(\d+)$/))) {
      const a = articles.find(x => x.id == m[1]);
      if (!a) throw new Error('内容不存在');
      if (method === 'GET') return withBody(a, true);
      if (method === 'PATCH') { Object.assign(a, body); a.updated_at = new Date().toISOString(); return withBody(a, true); }
      if (method === 'DELETE') { articles = articles.filter(x => x.id != m[1]); return { ok: true }; }
    }

    /* ---- 监测 ---- */
    if (p === '/monitor/queries' && method === 'GET') return mqueries;
    if (p === '/monitor/queries' && method === 'POST') {
      const t = { id: nid(), question: body.question, qgroup: body.qgroup || '场景', market: body.market || 'cn', brand_in_question: !!body.brand_in_question, active: true, tags: body.tags || [] };
      mqueries.push(t); return { id: t.id };
    }
    if ((m = p.match(/^\/monitor\/queries\/(\d+)$/))) {
      const t = mqueries.find(x => x.id == m[1]);
      if (method === 'PATCH' && t) { t.active = !t.active; return { active: t.active }; }
      if (method === 'DELETE') { mqueries = mqueries.filter(x => x.id != m[1]); return { ok: true }; }
    }
    if (p === '/monitor/engines' && method === 'GET') {
      return [
        { name: 'DeepSeek', model: 'deepseek-chat', market: 'cn' },
        { name: '豆包', model: 'doubao-seed-1-6', market: 'cn' },
        { name: '千问', model: 'qwen-max', market: 'cn' },
        { name: '元宝', model: 'yuanbao', market: 'cn' },
      ];
    }
    if (p === '/monitor/runs' && method === 'GET') return runs.slice().reverse();
    if (p === '/monitor/runs' && method === 'POST') {
      const times = Math.max(1, Math.min(5, body.times || 1));
      const pool = mqueries.filter(x => x.active && (!body.query_ids || body.query_ids.includes(x.id)));
      const n = Math.min(12, pool.length);
      const engines = (body.engine_names && body.engine_names.length) ? body.engine_names : ['DeepSeek', '豆包', '千问', '元宝'];
      const run = { id: nid(), brand_id: 1, status: 'running', total: n * engines.length * times, done: 0, started_at: new Date().toISOString(), finished_at: '' };
      runs.push(run);
      // 模拟后台采样进度
      const timer = setInterval(() => {
        run.done = Math.min(run.total, run.done + 2);
        if (run.done >= run.total) { run.status = 'completed'; run.finished_at = new Date().toISOString(); clearInterval(timer); }
      }, 900);
      return { id: run.id, total: run.total, queries: n, times };
    }
    if ((m = p.match(/^\/monitor\/runs\/(\d+)$/)) && method === 'GET') {
      const r = runs.find(x => x.id == m[1]);
      if (!r) throw new Error('采样批次不存在');
      return r;
    }
    if (p === '/monitor/samples' && method === 'GET') {
      if (SNAP) {
        const rid = +(q.run_id || 0);
        let ss = SNAP.samples.filter(s => s.run_id === rid);
        if (q.query_id) ss = ss.filter(s => s.query_id === +q.query_id);
        return ss;
      }
      return genSamples(+q.query_id, +(q.run_id || 3));
    }
    if (p === '/monitor/analysis' && method === 'GET') {
      const doneRuns = runs.filter(r => r.status === 'completed');
      const rid = q.run_id ? +q.run_id : (doneRuns.length ? Math.max(...doneRuns.map(r => r.id)) : 3);
      return buildAnalysis(rid);
    }

    /* ---- 设置 ---- */
    if (p === '/settings/llm' && method === 'GET') return { providers: llmProviders.map(x => ({ ...x })), env_providers: [] };
    if (p === '/settings/llm' && method === 'PUT') { llmProviders = (body.providers || []).map(x => ({ ...x })); return { saved: llmProviders.length }; }
    if (p === '/settings/llm/test' && method === 'POST') {
      await delay(700);
      return { results: llmProviders.map(x => ({ name: x.name, model: x.model, ok: x.name !== 'doubao', error: x.name === 'doubao' ? 'API Key 未配置' : '' })) };
    }
    if (p === '/settings/channels' && method === 'GET') return channels;
    if (p === '/settings/channels' && method === 'PUT') { channels = body; return { saved: channels.length }; }

    throw new Error('Mock 未覆盖的接口: ' + method + ' ' + path);
  };
})();
