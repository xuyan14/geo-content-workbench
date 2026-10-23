/* GEO 知识治理演示数据（虚构平台政策卡）*/
window.WB_KNOWLEDGE_CARDS = {
 "summary": {
  "total_cards": 10,
  "total_source_docs": 10,
  "channels": [
   {"id": "external_pages", "name": "外部网页抓取（按 URL 抓正文）", "source_type": "官方"}
  ]
 },
 "demo_cards": [
  {
   "card_id": "C-demo0001",
   "title": "7 天无理由退货的适用范围",
   "topics": [
    "售后与退换"
   ],
   "categories": [],
   "time": "2026",
   "doc_time": "2026",
   "content": "7 天无理由退货自签收次日起算，适用于吊牌完整、未洗涤穿着的商品；定制类、贴身内衣及食品等特殊品类不支持无理由退货。退货地址以下单页展示为准。",
   "cautions": [
    "特价清仓商品是否支持无理由退货以商品详情页标注为准"
   ],
   "sources": [
    {
     "doc_id": "external_pages:policy-0001",
     "doc_title": "7 天无理由退货的适用范围",
     "url": "https://www.starselect.example.com/help/policy-0001.html",
     "publisher": "星野优选（虚构演示）",
     "source_type": "官方",
     "pid": "P001",
     "pub_time": "2026",
     "quote": "（演示引文）以官方页面实际内容为准。"
    }
   ],
   "source_types": [
    "官方"
   ],
   "status": "已确认",
   "topics_proposed": [],
   "conflicts": [],
   "merged_from": [],
   "version": 1,
   "created_at": "2026-09-20T10:00:00",
   "updated_at": "2026-09-25T10:00:00",
   "change_log": [],
   "quality": "免审"
  },
  {
   "card_id": "C-demo0002",
   "title": "正品保险赔付流程",
   "topics": [
    "正品保障"
   ],
   "categories": [],
   "time": "2026",
   "doc_time": "2026",
   "content": "商品由品牌方授权供货，平台投保正品保险；如收到假冒商品，凭质检机构鉴定报告可申请假一赔十赔付，审核通过后赔付至原支付账户。",
   "cautions": [],
   "sources": [
    {
     "doc_id": "external_pages:policy-0002",
     "doc_title": "正品保险赔付流程",
     "url": "https://www.starselect.example.com/help/policy-0002.html",
     "publisher": "星野优选（虚构演示）",
     "source_type": "官方",
     "pid": "P001",
     "pub_time": "2026",
     "quote": "（演示引文）以官方页面实际内容为准。"
    }
   ],
   "source_types": [
    "官方"
   ],
   "status": "已确认",
   "topics_proposed": [],
   "conflicts": [],
   "merged_from": [],
   "version": 1,
   "created_at": "2026-09-20T10:00:00",
   "updated_at": "2026-09-25T10:00:00",
   "change_log": [],
   "quality": "免审"
  },
  {
   "card_id": "C-demo0003",
   "title": "大促折扣与日常折扣的关系",
   "topics": [
    "促销与活动"
   ],
   "categories": [],
   "time": "2026",
   "doc_time": "2026",
   "content": "大促期间的折扣以活动页公示为准，通常不与日常优惠券叠加；部分品类在大促前 7 天会有价格保护机制，降价可申请差价补偿。",
   "cautions": [],
   "sources": [
    {
     "doc_id": "external_pages:policy-0003",
     "doc_title": "大促折扣与日常折扣的关系",
     "url": "https://www.starselect.example.com/help/policy-0003.html",
     "publisher": "星野优选（虚构演示）",
     "source_type": "官方",
     "pid": "P001",
     "pub_time": "2026",
     "quote": "（演示引文）以官方页面实际内容为准。"
    }
   ],
   "source_types": [
    "官方",
    "外部"
   ],
   "status": "待确认",
   "topics_proposed": [],
   "conflicts": [
    {
     "field": "价格保护时长",
     "own": "大促前 7 天",
     "other": "大促前 15 天（外部转载口径）",
     "other_card_id": "C-demo0004"
    }
   ],
   "merged_from": [],
   "version": 1,
   "created_at": "2026-09-20T10:00:00",
   "updated_at": "2026-09-25T10:00:00",
   "change_log": [],
   "quality": "抽检"
  },
  {
   "card_id": "C-demo0004",
   "title": "价格保护时长（外部口径）",
   "topics": [
    "促销与活动"
   ],
   "categories": [],
   "time": "2026",
   "doc_time": "2026",
   "content": "（外部转载口径，待与官方核对）有观点认为价格保护覆盖大促前 15 天，实际以平台官方规则页为准。",
   "cautions": [],
   "sources": [
    {
     "doc_id": "external_pages:promo-external",
     "doc_title": "大促价格保护说明",
     "url": "https://www.starselect.example.com/help/promo-external.html",
     "publisher": "星野优选（虚构演示）",
     "source_type": "转载",
     "pid": "P001",
     "pub_time": "2026",
     "quote": "（演示引文）以官方页面实际内容为准。"
    }
   ],
   "source_types": [
    "外部"
   ],
   "status": "待确认",
   "topics_proposed": [],
   "conflicts": [],
   "merged_from": [],
   "version": 1,
   "created_at": "2026-09-20T10:00:00",
   "updated_at": "2026-09-25T10:00:00",
   "change_log": [],
   "quality": "必审"
  },
  {
   "card_id": "C-demo0005",
   "title": "换货申请与二次售后规则",
   "topics": [
    "售后与退换"
   ],
   "categories": [],
   "time": "2026",
   "doc_time": "2026",
   "content": "换货申请取消后，售后期内仍可再次发起；换货新商品若仍有问题可申请退货但不可再次换货；收货地址在仓库打包前可修改。",
   "cautions": [
    "换货新商品二次售后仅支持退货",
    "发货后不支持修改收货地址"
   ],
   "sources": [
    {
     "doc_id": "external_pages:policy-0005",
     "doc_title": "换货申请与二次售后规则",
     "url": "https://www.starselect.example.com/help/policy-0005.html",
     "publisher": "星野优选（虚构演示）",
     "source_type": "官方",
     "pid": "P001",
     "pub_time": "2026",
     "quote": "（演示引文）以官方页面实际内容为准。"
    }
   ],
   "source_types": [
    "官方"
   ],
   "status": "已确认",
   "topics_proposed": [],
   "conflicts": [],
   "merged_from": [],
   "version": 1,
   "created_at": "2026-09-20T10:00:00",
   "updated_at": "2026-09-25T10:00:00",
   "change_log": [],
   "quality": "免审"
  },
  {
   "card_id": "C-demo0006",
   "title": "配送时效与范围",
   "topics": [
    "物流配送"
   ],
   "categories": [],
   "time": "2026",
   "doc_time": "2026",
   "content": "默认顺丰配送，主要城市次日达；偏远地区 3-5 日；大促期间时效可能延长 1-2 天，以订单页展示的预计送达时间为准。",
   "cautions": [],
   "sources": [
    {
     "doc_id": "external_pages:policy-0006",
     "doc_title": "配送时效与范围",
     "url": "https://www.starselect.example.com/help/policy-0006.html",
     "publisher": "星野优选（虚构演示）",
     "source_type": "官方",
     "pid": "P001",
     "pub_time": "2026",
     "quote": "（演示引文）以官方页面实际内容为准。"
    }
   ],
   "source_types": [
    "官方"
   ],
   "status": "待确认",
   "topics_proposed": [],
   "conflicts": [],
   "merged_from": [],
   "version": 1,
   "created_at": "2026-09-20T10:00:00",
   "updated_at": "2026-09-25T10:00:00",
   "change_log": [],
   "quality": "抽检"
  },
  {
   "card_id": "C-demo0007",
   "title": "会员等级与权益",
   "topics": [
    "会员体系"
   ],
   "categories": [],
   "time": "2026",
   "doc_time": "2026",
   "content": "会员按年度消费累计升级，等级越高折扣与免邮次数越多；生日月有专属优惠券；权益次年 1 月重置。",
   "cautions": [],
   "sources": [
    {
     "doc_id": "external_pages:policy-0007",
     "doc_title": "会员等级与权益",
     "url": "https://www.starselect.example.com/help/policy-0007.html",
     "publisher": "星野优选（虚构演示）",
     "source_type": "官方",
     "pid": "P001",
     "pub_time": "2026",
     "quote": "（演示引文）以官方页面实际内容为准。"
    }
   ],
   "source_types": [
    "官方"
   ],
   "status": "已确认",
   "topics_proposed": [],
   "conflicts": [],
   "merged_from": [],
   "version": 1,
   "created_at": "2026-09-20T10:00:00",
   "updated_at": "2026-09-25T10:00:00",
   "change_log": [],
   "quality": "免审"
  },
  {
   "card_id": "C-demo0008",
   "title": "客服响应时效",
   "topics": [
    "客户服务"
   ],
   "categories": [],
   "time": "",
   "doc_time": "2026",
   "content": "在线客服 7×24 小时响应，高峰期排队可能超过 5 分钟；电话客服工作日 9:00-21:00。",
   "cautions": [],
   "sources": [
    {
     "doc_id": "external_pages:policy-0008",
     "doc_title": "客服响应时效",
     "url": "https://www.starselect.example.com/help/policy-0008.html",
     "publisher": "星野优选（虚构演示）",
     "source_type": "官方",
     "pid": "P001",
     "pub_time": "2026",
     "quote": "（演示引文）以官方页面实际内容为准。"
    }
   ],
   "source_types": [
    "官方"
   ],
   "status": "待确认",
   "topics_proposed": [],
   "conflicts": [],
   "merged_from": [],
   "version": 1,
   "created_at": "2026-09-20T10:00:00",
   "updated_at": "2026-09-25T10:00:00",
   "change_log": [],
   "quality": "抽检"
  },
  {
   "card_id": "C-demo0009",
   "title": "尺码选择建议",
   "topics": [
    "选购指南"
   ],
   "categories": [],
   "time": "2026",
   "doc_time": "2026",
   "content": "服饰鞋包品类建议参考商品详情页的尺码表与试穿报告；不同品牌尺码差异较大，正装建议比日常码大半码。",
   "cautions": [],
   "sources": [
    {
     "doc_id": "external_pages:policy-0009",
     "doc_title": "尺码选择建议",
     "url": "https://www.starselect.example.com/help/policy-0009.html",
     "publisher": "星野优选（虚构演示）",
     "source_type": "官方",
     "pid": "P001",
     "pub_time": "2026",
     "quote": "（演示引文）以官方页面实际内容为准。"
    }
   ],
   "source_types": [
    "官方"
   ],
   "status": "待确认",
   "topics_proposed": [],
   "conflicts": [],
   "merged_from": [
    "C-demo0010"
   ],
   "version": 1,
   "created_at": "2026-09-20T10:00:00",
   "updated_at": "2026-09-25T10:00:00",
   "change_log": [],
   "quality": "抽检"
  },
  {
   "card_id": "C-demo0010",
   "title": "退换货运费承担规则",
   "topics": [
    "售后与退换"
   ],
   "categories": [
    "运费规则"
   ],
   "time": "2026",
   "doc_time": "2026",
   "content": "质量问题退换货运费由平台承担；无理由退货运费由消费者承担，会员每月有 2 次免邮额度。",
   "cautions": [],
   "sources": [
    {
     "doc_id": "external_pages:policy-0010",
     "doc_title": "退换货运费承担规则",
     "url": "https://www.starselect.example.com/help/policy-0010.html",
     "publisher": "星野优选（虚构演示）",
     "source_type": "官方",
     "pid": "P001",
     "pub_time": "2026",
     "quote": "（演示引文）以官方页面实际内容为准。"
    }
   ],
   "source_types": [
    "官方"
   ],
   "status": "已确认",
   "topics_proposed": [],
   "conflicts": [],
   "merged_from": [],
   "version": 1,
   "created_at": "2026-09-20T10:00:00",
   "updated_at": "2026-09-25T10:00:00",
   "change_log": [],
   "quality": "免审"
  }
 ]
};
