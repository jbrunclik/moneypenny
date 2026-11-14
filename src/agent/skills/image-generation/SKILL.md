---
name: image-generation
description: Calling generate_image - writing the prompt, image size and search grounding, what the image model cannot do, editing uploads and history images, and keeping a person's likeness. Load BEFORE the first generate_image call of a turn.
---
# Image generation

For image prompts, be specific and detailed:
- Include style (photorealistic, cartoon, watercolor, oil painting, etc.)
- Describe colors, lighting, composition, mood, and atmosphere
- If text should appear in the image, specify it clearly
- For modifications, describe the complete desired result, not just the changes
- Use image_size="2K" for sharper results (same price as 1K); "4K" only for print or when asked
- Use use_search=True when the image depends on real-world or current facts (weather, events, real places or products)

**What the image model can and cannot do:**
generate_image is instruction-based: it takes a text prompt plus reference images and regenerates the WHOLE image.
It has NO inpainting masks, denoising strength, seed, negative prompt, ControlNet, or IP-Adapter/FaceID controls -
never tell the user to set these, and never claim pixels will stay "untouched".
For edits that must preserve a person's likeness (e.g. relighting a profile photo):
- State explicitly what must NOT change: "keep the person's face, facial features, expression, skin texture, hair, and clothing identical; no retouching or beautifying"
- State the ONLY things to change (lighting direction/softness, color grading, background blur)
- Prefer one small change per turn; tell the user to compare the result and that subtle likeness drift is possible
- If the user needs a guaranteed-identical face, recommend a photo editor (e.g. Lightroom) instead

**Image Editing (with current uploads):**
When the user uploads an image in the current message and asks you to modify it:
- Use reference_images="all" to include the uploaded image(s) as reference
- Or use reference_images="0" for the first image, "0,1" for first two, etc.
- The prompt should describe the desired modification or transformation
- Example: User uploads a photo and says "make me look like a wizard"
  → Call generate_image(prompt="Transform the person in the photo into a wizard with a magical hat, robes, and mystical aura", reference_images="all")

**Image Editing (with images from conversation history):**
When the user asks you to modify an image they uploaded earlier in the conversation:
1. Check the conversation history metadata for file IDs (format: `"id":"message_id:file_index"`)
2. Use the message_id and file_index directly with generate_image
- Example: User says "modify that photo I sent earlier to make me look like an astronaut"
  → Check history: the user's message has `"files":[{"name":"photo.jpg","type":"image","id":"msg-abc:0"}]`
  → Call: generate_image(prompt="Transform the person into an astronaut...", history_image_message_id="msg-abc", history_image_file_index=0)

**Combining history images with current uploads:**
You can use BOTH history_image_* parameters AND reference_images together to combine images from different messages.
