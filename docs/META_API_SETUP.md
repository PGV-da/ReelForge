# Meta Instagram Graph API Setup Guide

> Step-by-step guide to obtaining the `IG_USER_ID` and a Long-Lived Access Token for the ReelForge Instagram publishing feature.

---

## Table of Contents

1. [Convert to Instagram Professional Account](#1-convert-to-instagram-professional-account)
2. [Create a Facebook Page & Link Instagram](#2-create-a-facebook-page--link-instagram)
3. [Create a Meta Developer App](#3-create-a-meta-developer-app)
4. [Add Instagram Graph API Product](#4-add-instagram-graph-api-product)
5. [Generate a User Access Token](#5-generate-a-user-access-token)
6. [Exchange for a Long-Lived Token](#6-exchange-for-a-long-lived-token)
7. [Find Your IG_USER_ID](#7-find-your-ig_user_id)
8. [Token Refresh Strategy](#8-token-refresh-strategy)
9. [Required Permissions](#9-required-permissions)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Convert to Instagram Professional Account

Your Instagram account **must** be a Professional Account (Business or Creator) to use the Content Publishing API.

1. Open the **Instagram app** on your phone
2. Go to **Settings** → **Account** → **Switch to Professional Account**
3. Choose either **Business** or **Creator** (both work)
4. Select a category for your profile
5. Complete the setup wizard

> ⚠️ **Important:** Your profile must be **Public** (not Private) for the API to work.

---

## 2. Create a Facebook Page & Link Instagram

The Instagram Graph API operates through Facebook Pages. You need a linked Page.

1. Go to [facebook.com/pages/create](https://www.facebook.com/pages/create)
2. Create a new Page (or use an existing one)
3. Go to your Page → **Settings** → **Linked Accounts** → **Instagram**
4. Click **Connect Account** and log in with your Instagram credentials
5. Authorize the connection

### Verify the Link

- On Instagram: **Settings** → **Account** → **Linked Accounts** → you should see your Facebook Page
- On Facebook: **Page Settings** → **Instagram** → your account should appear

---

## 3. Create a Meta Developer App

1. Go to [developers.facebook.com](https://developers.facebook.com/)
2. Click **My Apps** → **Create App**
3. Choose app type: **Business** (recommended) or **None**
4. Fill in:
   - **App Name:** `ReelForge Bot` (or any name)
   - **Contact Email:** Your email
   - **Business Portfolio:** Select or create one
5. Click **Create App**

---

## 4. Add Instagram Graph API Product

1. In your app dashboard, click **Add Product**
2. Find **Instagram Graph API** and click **Set Up**
3. This adds the Instagram API product to your app

---

## 5. Generate a User Access Token

### Method A: Graph API Explorer (Recommended for Setup)

1. Go to [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
2. Select your **App** from the dropdown
3. Click **Generate Access Token**
4. When prompted, grant these permissions:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
5. Click **Generate** — you'll receive a **Short-Lived Token** (valid ~1 hour)

### Method B: App Settings

1. Go to your app's **Settings** → **Basic**
2. Note your **App ID** and **App Secret** (you'll need these for token exchange)

---

## 6. Exchange for a Long-Lived Token

Short-lived tokens expire in ~1 hour. Exchange them for a **60-day Long-Lived Token**.

### Step 1: Exchange Short-Lived → Long-Lived

```bash
curl -X GET "https://graph.facebook.com/v26.0/oauth/access_token?\
grant_type=fb_exchange_token&\
client_id=YOUR_APP_ID&\
client_secret=YOUR_APP_SECRET&\
fb_exchange_token=YOUR_SHORT_LIVED_TOKEN"
```

Response:
```json
{
  "access_token": "EAAG...(long string)...ZD",
  "token_type": "bearer",
  "expires_in": 5184000
}
```

The `access_token` in the response is your **Long-Lived Token** (valid for 60 days).

### Step 2: Save to `.env`

```env
IG_ACCESS_TOKEN=EAAG...(your long-lived token)...ZD
```

### Step 3: Verify the Token

```bash
curl -X GET "https://graph.facebook.com/debug_token?\
input_token=YOUR_LONG_LIVED_TOKEN&\
access_token=YOUR_LONG_LIVED_TOKEN"
```

Or use the bot's `/token_health` command after setup.

---

## 7. Find Your IG_USER_ID

The `IG_USER_ID` is the **numeric ID** of your Instagram Professional Account (not your username).

### Method 1: Via API

```bash
# First, get your Facebook Pages
curl -X GET "https://graph.facebook.com/v26.0/me/accounts?\
fields=id,name,instagram_business_account&\
access_token=YOUR_LONG_LIVED_TOKEN"
```

Response:
```json
{
  "data": [
    {
      "id": "PAGE_ID",
      "name": "Your Page Name",
      "instagram_business_account": {
        "id": "17841400123456789"  ← This is your IG_USER_ID
      }
    }
  ]
}
```

### Method 2: Graph API Explorer

1. Go to [Graph API Explorer](https://developers.facebook.com/tools/explorer/)
2. Select your app and paste your Long-Lived Token
3. Enter: `me/accounts?fields=instagram_business_account`
4. Click **Submit**
5. Find the `instagram_business_account.id` — that's your `IG_USER_ID`

### Save to `.env`

```env
IG_USER_ID=17841400123456789
```

---

## 8. Token Refresh Strategy

Long-Lived Tokens expire after **60 days**. You must refresh them before expiry.

### Refresh a Long-Lived Token

```bash
curl -X GET "https://graph.facebook.com/v26.0/oauth/access_token?\
grant_type=fb_exchange_token&\
client_id=YOUR_APP_ID&\
client_secret=YOUR_APP_SECRET&\
fb_exchange_token=YOUR_CURRENT_LONG_LIVED_TOKEN"
```

> 💡 **Tip:** Set a calendar reminder for every 50 days to refresh your token. Use the bot's `/token_health` command to check expiry.

### Rules for Refreshing

- You can refresh a Long-Lived Token **at any time** before it expires
- Each refresh generates a **new** 60-day token
- The old token becomes invalid once a new one is generated
- You **cannot** refresh an already-expired token — you'll need to generate a new Short-Lived Token from scratch

---

## 9. Required Permissions

| Permission | Required For |
| :--- | :--- |
| `instagram_basic` | Reading account information |
| `instagram_content_publish` | Publishing Reels and Posts |
| `pages_show_list` | Listing connected Facebook Pages |
| `pages_read_engagement` | Reading Page metadata |

### For Apps in Development Mode

- Only works for users with a **role** in the app (Admin, Developer, Tester)
- Limited to **25 publishes per day**
- No App Review required

### For Production (Live Mode)

- Requires **App Review** by Meta
- Submit for review of `instagram_content_publish` permission
- Unlimited publishing (subject to rate limits)

---

## 10. Troubleshooting

### Common Errors

| Error | Cause | Solution |
| :--- | :--- | :--- |
| `OAuthException: Invalid access token` | Token expired or malformed | Generate a new token (Steps 5-6) |
| `instagram_business_account is null` | IG not linked to FB Page | Re-link Instagram to your Facebook Page (Step 2) |
| `(#10) Not enough permissions` | Missing required permissions | Re-generate token with correct permissions (Step 5) |
| `Publishing not allowed` | Account is Personal, not Professional | Convert to Professional Account (Step 1) |
| `Resumable upload not supported` | Wrong API version or parameters | Ensure `upload_type=resumable` and API `v26.0+` |
| `Container status: ERROR` | Video format/size issues | Check video meets IG requirements (1080x1920, <100MB, 3-90s) |

### Instagram Reels Requirements

| Parameter | Requirement |
| :--- | :--- |
| **Aspect Ratio** | 9:16 (vertical) |
| **Resolution** | 1080x1920 recommended |
| **Duration** | 3 seconds to 15 minutes |
| **File Size** | Max 1GB |
| **Format** | MP4 with H.264 video, AAC audio |
| **Frame Rate** | 24-60 fps |

### Debug Commands

```bash
# Test token validity
curl "https://graph.facebook.com/debug_token?input_token=TOKEN&access_token=TOKEN"

# List connected IG accounts
curl "https://graph.facebook.com/v26.0/me/accounts?fields=instagram_business_account&access_token=TOKEN"

# Check IG account info
curl "https://graph.facebook.com/v26.0/IG_USER_ID?fields=username,name&access_token=TOKEN"
```
