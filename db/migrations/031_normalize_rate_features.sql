-- 将 rate 类特征从百分比（×100）还原为原始比率，避免对模型施加人工缩放
UPDATE creator_features
   SET social_engagement_rate = social_engagement_rate / 100.0,
       conversation_rate = conversation_rate / 100.0,
       fanart_ratio = fanart_ratio / 100.0,
       mention_rate = mention_rate / 100.0
 WHERE social_engagement_rate IS NOT NULL
    OR conversation_rate IS NOT NULL
    OR fanart_ratio IS NOT NULL
    OR mention_rate IS NOT NULL;
