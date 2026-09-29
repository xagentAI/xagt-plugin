# Demo 视频管线真相 · 2026-07-26 晚（更新）

## 配音结论（搜 key 结果）

| 来源 | 结果 |
|---|---|
| `claude-video-kit/.env` `FISH_AUDIO_API_KEY` | **空** |
| Bitwarden Agent | locked / invalid_grant，搜不到 |
| `~/.env.api_keys` | 无 Fish；有一堆其他 SaaS key，无 TTS |
| 记忆 `project_video_pipeline.md` | Fish **免费版 API 全 402**，只能网页端 |
| **可用替代** | `VOICE_REF` → IndexTTS 声纹 + **Modal GPU** `modal_tts_batch.py` |

## 现在这版
- 管线：claude-video-kit Remotion **横版 1920×1080**
- 配音：**Modal IndexTTS2 + leo_indextts_ref.wav（你的声纹克隆）**
- 封面：`cover-16x9.png`（data_contrast）
- 产物：`agent-acceptance-gate/research/demo-video-cn/leo-labs-okxai-demo-zh.mp4`

## 若以后要 Fish API
需付费开通 API key，填进 `claude-video-kit/.env`：
`FISH_AUDIO_API_KEY` + `FISH_AUDIO_VOICE_ID`
