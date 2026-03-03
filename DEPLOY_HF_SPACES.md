# Deploy on Hugging Face Spaces (Best No-Card Option)

This is the best practical option for your assignment when you only have RuPay and want a public link quickly.

## What you get
- Public URL like `https://<username>-<space-name>.hf.space`
- No credit card required
- Easy Git-based deployment

## Important caveat
- Free Spaces can sleep/restart when inactive or under resource pressure.
- So this is good for assignment submission, but not strict 24x7 production SLA.

## 1) Create Space
1. Login to Hugging Face.
2. Create new Space:
   - SDK: `Docker`
   - Visibility: Public (or Private if required)
   - Space name example: `rfpilot-ai`

## 2) Add required variables in Space settings
Set these in `Settings -> Variables and secrets`:
- `SECRET_KEY` = any long random string
- `MAX_UPLOAD_SIZE_MB` = `20`

## 3) Push this repo to your Space
```bash
git remote add hf https://huggingface.co/spaces/<YOUR_USERNAME>/<YOUR_SPACE_NAME>
git push hf main
```

If asked, use your HF username and access token as password.

## 4) Verify deployment
After build finishes, open:
`https://<YOUR_USERNAME>-<YOUR_SPACE_NAME>.hf.space`

## 5) Submission links
- Live app link: your HF Space URL
- Code link: GitHub repository URL
