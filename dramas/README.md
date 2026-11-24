# AI C-Drama Slate: 5 Ready-to-Produce Stories

Five original short dramas in the genres doing best on YouTube's AI-made C-drama channels. Each file is a complete production package:

- **YouTube package**: 3 title options, description, tags, thumbnail prompt and thumbnail text
- **Cold open**: the first 15 seconds, flashing forward to the climax so viewers don't click away
- **Style lock**: one style string added to every image prompt, so the whole video looks like one show
- **Cast**: a locked appearance prompt for each character, so faces stay consistent from scene to scene
- **Script**: 6 parts and about 30–36 scenes, each with an image prompt, a motion prompt, narration, dialogue and sound cues
- **Sequel hook and notes**: why each beat works

| # | File | Genre | Hook in one line |
|---|------|-------|------------------|
| 1 | [01-hundredfold-return-system.md](01-hundredfold-return-system.md) | Urban System | Dumped delivery rider gets a system that pays back 100x everything he gives away |
| 2 | [02-reborn-real-heiress.md](02-reborn-real-heiress.md) | True vs Fake Heiress / Rebirth Revenge | She died alone in the snow while her rich family partied, then woke up on the day they came to take her in |
| 3 | [03-ceo-divorce-regret.md](03-ceo-divorce-regret.md) | CEO Divorce Regret / Hidden Identity | For three years he never knew his quiet wife was the surgeon who gave him back his sight |
| 4 | [04-ice-apocalypse-hoarding.md](04-ice-apocalypse-hoarding.md) | Apocalypse Hoarding / Rebirth | Locked out to freeze by her boyfriend and best friend, she's reborn 30 days before the ice, with a storage space |
| 5 | [05-villainess-bullet-comments.md](05-villainess-bullet-comments.md) | Palace Romance / Bullet-Comment Awakening | She suddenly sees readers' comments, and they say she's the villainess who gets beheaded in 3 chapters |

**Suggested release order:** 3, then 1, 5, 2, 4. CEO divorce regret and System stories pull the broadest audiences, so lead with them. The villainess story has the most distinctive visual gimmick. The two rebirth stories do well back to back.

---

## Production pipeline (per drama)

Each video runs about 12–16 minutes, in 16:9. Every Part also works as a 9:16 Short.

1. **Characters first.** Generate each cast member from their locked appearance prompt plus the style lock. Pick one face and save it as the **character reference**. Then use your tool's character or face reference feature (Midjourney `--cref`/omni-reference, Flux/Kontext reference, Kling Elements, Seedream/Seedance references) for every later shot. Consistent faces are the biggest quality signal in AI dramas.
2. **Images.** For each scene, combine the `🎬 Image` prompt and the style lock. Make 2–4 variations or angles per scene (wide, medium, close-up on the face), so a 25–40 second scene has 4–8 cuts.
3. **Motion.** Feed the best stills to an image-to-video model (Kling, Hailuo/MiniMax, Veo, Seedance, Runway) with the `🎥 Motion` prompt. Clips of 5 seconds are enough. Animate the emotional or reveal shots, and give quieter shots a slow zoom or pan in the editor.
4. **Voice.** Record or TTS (ElevenLabs, CapCut, etc.) the `NARRATOR` lines in one consistent voice per drama, at roughly 150–165 words per minute. You can either have the narrator read the dialogue with small tone shifts, or give the main characters their own voices. Both styles are common.
5. **Edit.** CapCut or Premiere. Burn in subtitles; viewers expect them. Put `[SYSTEM]`, `[ON SCREEN]` and `💬 COMMENTS` overlays in as text animations. Never generate them inside the image, because AI text comes out garbled. Use a 0.3-second "whoosh" plus a zoom punch on every face-slap reveal. Cut music to silence for one beat before big lines.
6. **Shorts.** Each `### Part` ends on a cliffhanger. Export each Part as a 9:16 Short (crop or reframe) that ends with "Full story on my channel".

### Retention rules all five scripts follow
- Open with the climax (cold open), then go back: "Three months earlier…"
- A reversal or reveal roughly every 60–90 seconds
- The villain gets their comeuppance on screen, with people watching. Public humiliation is the payoff the genre promises
- Every Part ends on an unanswered question
- Each one ends with a sequel tease, ready for Part 2 if it performs

### Platform notes
- **Label AI content.** YouTube requires creators to disclose realistic altered or synthetic content. Turn on the "altered or synthetic content" setting when you upload.
- **Monetization.** YouTube can limit monetization for mass-produced, repetitive content. Original scripts, a consistent channel voice and real editing (not just a slideshow) keep you on the right side of that. These scripts are original, so keep the edit original too.
- Character names are invented, and no real people, brands or existing dramas are depicted. Keep it that way in your prompts, too: no celebrity names for faces.
