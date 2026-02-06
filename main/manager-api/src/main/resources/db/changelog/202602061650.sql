-- 统一规范ai_tts_voice语言类型数据
UPDATE ai_tts_voice
SET languages = CASE
    WHEN languages IN ('中文', '普通话','东北话','天津话','中文-北京口音','中文-青岛口音','中文-河南口音','中文-广西口音','辽宁','陕西','中文-四川口音','中文-台湾口音','中文-长沙口音') THEN '普通话'
    WHEN languages IN ('中文及中英文混合', '中文、英文', '中文、美式英语','中文-北京口音、英文','中文(东北)及中英文混合') THEN '普通话、英语'
    WHEN languages IN ('英式英文', '英式英语', '美式英语', '澳洲英语', '英文') THEN '英语'
    WHEN languages = '日语' THEN '日语'
    WHEN languages = '日语、西语' THEN '日语、西班牙语'
    WHEN languages = '韩语' THEN '韩语'
    WHEN languages IN ('粤语', '中文-广东口音') THEN '粤语'
    WHEN languages = '中文(粤语)及中英文混合' THEN '粤语、英语'
    WHEN languages = '粤语及粤英混合' THEN '粤语、英语'
    ELSE languages
END;