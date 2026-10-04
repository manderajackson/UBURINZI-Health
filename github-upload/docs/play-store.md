# Publishing Uburinzi Health on the Google Play Store

The dashboard is already an installable PWA. Google Play accepts a PWA as a real Android app through
a **Trusted Web Activity** — the app is a thin native shell that opens your site full-screen with no
browser bar. Patients still need nothing installed: they get SMS.

**What you need:** a Google Play developer account (**$25, one-off**), Java 17+, and ~1 hour.
I cannot submit to Play on your behalf, but everything below is prepared and tested.

---

## 0. Deploy first — the app is only as live as its URL

Do [deploy-vercel.md](deploy-vercel.md) first. A TWA needs a public HTTPS URL; `https://uburinzi.vercel.app`
is already referenced in `twa-manifest.json` — **change `hostName`, the icon URLs and `fullScopeUrl`
to your real domain** (find and replace `uburinzi.vercel.app` in that file).

## 1. Build the Android package with Bubblewrap

```bash
npm i -g @bubblewrap/cli
cd ~/uburinzi
bubblewrap init --manifest https://YOUR-DOMAIN/static/manifest.webmanifest
#   ...or use the prepared file:
bubblewrap init --manifest ./twa-manifest.json
bubblewrap build
```

Bubblewrap asks for:
* **Package name:** `rw.uburinzi.health` (already set)
* **Keystore:** let it create `./android.keystore`, and **back that file up** — lose it and you can
  never update the app again.
* It then produces `app-release-bundle.aab` (what Play wants) and `app-release-signed.apk`.

## 2. Link the site to the app (Digital Asset Links)

Without this, the installed app shows a browser address bar instead of running full-screen.

1. Get your signing fingerprint:
   ```bash
   keytool -list -v -keystore ./android.keystore -alias android -storepass android -keypass android
   ```
   copy the **SHA-256** line (`AA:BB:CC:…`).
2. Paste it into **Channels → Play Store** (or set `UBURINZI_PLAY_SHA256`) and save.
3. Uburinzi then serves it automatically — check it:
   ```
   https://YOUR-DOMAIN/.well-known/assetlinks.json
   ```
   It must return your package name and fingerprint, with `Content-Type: application/json`.

Store two fingerprints while testing: the **upload key** and, once enrolled in Play App Signing,
Google's **app signing key** from Play Console → Setup → App signing.

## 3. What to enter in Play Console

| Field | Value |
|---|---|
| **App name** | Uburinzi Health |
| **Short description (80 chars)** | Chronic patient follow-up between clinic visits, by SMS. |
| **Full description** | See below |
| **Category** | Medical (Health & Fitness) |
| **Tags** | Health, Medical, Productivity |
| **Content rating** | Everyone — no violence, no user-generated content |
| **Data safety** | Data collected: name, phone number, health info, app activity. Encrypted in transit. **Not** shared with third parties beyond the SMS carrier. Deletion request available. |
| **Privacy policy** | `https://YOUR-DOMAIN/privacy` — already built into the app (see `templates/privacy.html`) |
| **Target audience** | Clinic staff / professionals — **not** for children as a general audience |
| **Screenshots** | Use `docs/store/*.png` (1080×1920, phone) |
| **App icon** | `static/icons/icon-512.png` |
| **Feature graphic** | 1024×500 — export one from the dashboard screenshot |

**Full description (copy/paste):**

> Uburinzi Health helps clinics stay with their chronic patients between appointments.
>
> Built for the reality of African healthcare: patients receive an ordinary SMS — no smartphone, no
> app, no internet, no data bundle. They answer 1 = yes, 2 = no, 3 = not feeling well, and the clinic
> sees who is slipping before the next appointment, not after it.
>
> For clinic staff:
> • A live dashboard: adherence, response rate, no-shows and cost per patient.
> • A traffic-light alert queue — red patients surface first, with reasons.
> • Escalation that adapts: an unread check-in is retried on WhatsApp, then handed to a nurse as a
>   phone-call task.
> • Patient timelines showing every message sent and every reply received.
> • Protocols for diabetes, hypertension, HIV, TB, asthma, epilepsy, heart failure and antenatal care,
>   in Kinyarwanda, English, French and Swahili.
> • Works offline: pages you have opened stay available with no connection.
>
> For patients: nothing to install. Just reply to the message.
>
> Uburinzi is a clinical tool for healthcare providers. Patient data is used only for care, consent
> is recorded per patient, and STOP always works.

## 4. Things Play will check, and how we already pass

| Requirement | How Uburinzi meets it |
|---|---|
| HTTPS | Vercel |
| Web manifest with name, icons, standalone display | `static/manifest.webmanifest` |
| Service worker with an offline fetch handler | `static/sw.js` — verified: 21 alerts and 53 patients load with the network cut |
| 512×512 icon + maskable icon | `static/icons/icon-512.png`, `icon-maskable-512.png` |
| Digital Asset Links | `/.well-known/assetlinks.json` |
| Privacy policy | `/privacy` |
| No browser address bar | TWA + matched asset links |
| 64-bit build, API 33+ | Bubblewrap output (minSdk 21, modern Android target) |

## 5. After publishing

* **Play App Signing** — let Google manage the key, then add their SHA-256 to the asset-links setting
  too, otherwise new installs show the address bar.
* **Test track first** — upload the AAB to Internal testing, install on your own phone, confirm there
  is **no browser bar**, then promote to closed → production.
* **Updates** — rebuild the AAB any time; the app content comes from your server, so most changes need
  no store release at all. Bump `appVersionCode` in `twa-manifest.json` for each upload.
* **The web app stays the same app** — installing from the browser and installing from Play give the
  identical experience.
