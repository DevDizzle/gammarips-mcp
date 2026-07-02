# PROMPT: Enable MCP Server Authentication

> **SUPERSEDED (2026-07-02):** This doc assumes an `src/auth/` module that no longer exists
> in the tree and stores key hashes on the webapp `users` collection. The current auth design
> (fresh build: `mcp_api_keys/{sha256}` collection, bearer tokens, tiers, shadow rollout) is
> Phase 2 of `docs/MCP-V3-SPEC.md`.

## Objective
Enable paid-only API access on the GammaRips MCP server. Users must have an active subscription to use the API.

---

## Current State

### What's Already Built (MCP Server)
- **Auth middleware:** `src/auth/middleware.py` — validates API keys against Firestore
- **API key generator:** `src/auth/api_key_generator.py` — creates `ps_live_{hex}` keys
- **Env var:** `REQUIRE_API_KEY=false` (disabled)
- **Expected collection:** `taas_users` with `api_key_hash`, `subscription_status`

### What's Missing
1. Webapp doesn't generate API keys for users
2. Webapp uses `users` collection, MCP expects `taas_users`
3. No UI for users to view/copy their API key
4. `REQUIRE_API_KEY` is `false` in production

---

## Implementation Plan

### Phase 1: Unify User Collections (Webapp)

**Option A (Recommended): Modify MCP to use webapp's `users` collection**

Edit `src/auth/middleware.py`:

```python
# Change default collection
self.users_collection = os.getenv("FIRESTORE_COLLECTION_USERS", "users")  # was "taas_users"

# Update validation query to check isSubscribed field
async def validate_api_key(self, api_key: str | None) -> dict:
    # ... existing code ...
    
    user_data = user_doc.to_dict()
    user_data["user_id"] = user_doc.id
    
    # Check subscription status (webapp uses isSubscribed boolean)
    is_subscribed = user_data.get("isSubscribed", False)
    
    # Also check trial period (proUntil timestamp)
    pro_until = user_data.get("proUntil")
    in_trial = False
    if pro_until:
        try:
            in_trial = pro_until.timestamp() > datetime.now().timestamp()
        except:
            pass
    
    if not is_subscribed and not in_trial:
        raise ValueError(
            "Subscription required. Subscribe at gammarips.com/account"
        )
    
    return user_data
```

Update `.env`:
```bash
FIRESTORE_COLLECTION_USERS=users  # Use webapp's collection
```

---

### Phase 2: Add API Key to Webapp User Schema

**File: `gammarips-webapp/src/lib/firebase.ts`** (External Repo)

Update `DbUser` type:
```typescript
export interface DbUser {
  // ... existing fields ...
  apiKey?: string;         // Plain key shown once on generation
  apiKeyHash?: string;     // SHA256 hash stored permanently
  apiKeyCreatedAt?: Timestamp;
}
```

**File: `gammarips-webapp/src/lib/api-key.ts` (new file)**

```typescript
import { sha256 } from 'js-sha256';

export function generateApiKey(): string {
  const randomBytes = crypto.getRandomValues(new Uint8Array(16));
  const hex = Array.from(randomBytes).map(b => b.toString(16).padStart(2, '0')).join('');
  return `gr_live_${hex}`;
}

export function hashApiKey(apiKey: string): string {
  return sha256(apiKey);
}
```

---

### Phase 3: API Key Generation UI (Webapp)

**File: `gammarips-webapp/src/app/account/page.tsx`**

Add "API Access" section:

```tsx
// After subscription status section
<section className="p-6 rounded-lg border bg-card space-y-4">
  <h2 className="text-xl font-bold">API Access</h2>
  
  {!dbUser?.apiKeyHash ? (
    <div className="space-y-4">
      <p className="text-muted-foreground">
        Generate an API key to connect your AI agent to GammaRips MCP.
      </p>
      <Button onClick={handleGenerateApiKey} disabled={!isPro}>
        Generate API Key
      </Button>
      {!isPro && (
        <p className="text-sm text-yellow-500">
          Subscribe to generate an API key.
        </p>
      )}
    </div>
  ) : (
    <div className="space-y-4">
      {newApiKey ? (
        <div className="p-4 bg-green-500/10 border border-green-500 rounded">
          <p className="text-sm font-semibold text-green-500 mb-2">
            ⚠️ Copy this key now — you won't see it again!
          </p>
          <code className="block p-2 bg-muted rounded text-sm break-all">
            {newApiKey}
          </code>
          <Button 
            variant="outline" 
            size="sm" 
            className="mt-2"
            onClick={() => navigator.clipboard.writeText(newApiKey)}
          >
            Copy to Clipboard
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            API key created: {dbUser.apiKeyCreatedAt?.toDate().toLocaleDateString()}
          </p>
          <p className="text-sm text-muted-foreground">
            Key prefix: <code className="text-primary">gr_live_****</code>
          </p>
          <Button variant="destructive" size="sm" onClick={handleRegenerateApiKey}>
            Regenerate Key
          </Button>
        </div>
      )}
    </div>
  )}
  
  <div className="pt-4 border-t">
    <p className="text-sm font-semibold mb-2">MCP Endpoint:</p>
    <code className="block p-2 bg-muted rounded text-sm">
      https://gammarips-mcp-469352939749.us-central1.run.app/sse
    </code>
  </div>
</section>
```

**Handler functions:**

```tsx
const [newApiKey, setNewApiKey] = useState<string | null>(null);

const handleGenerateApiKey = async () => {
  if (!user) return;
  
  const apiKey = generateApiKey();
  const apiKeyHash = hashApiKey(apiKey);
  
  // Update Firestore
  const userRef = doc(db, 'users', user.uid);
  await updateDoc(userRef, {
    apiKeyHash: apiKeyHash,
    apiKeyCreatedAt: serverTimestamp(),
  });
  
  // Show the key once
  setNewApiKey(apiKey);
};

const handleRegenerateApiKey = async () => {
  if (confirm("This will invalidate your existing API key. Continue?")) {
    setNewApiKey(null);
    await handleGenerateApiKey();
  }
};
```

---

### Phase 4: Update MCP Server for Header Auth

**File: `src/server.py`**

Add API key extraction from headers:

```python
from auth.middleware import auth_middleware

# In request handler
async def handle_request(request):
    # Extract API key from header
    api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
    
    # Validate
    try:
        user_info = await auth_middleware.validate_api_key(api_key)
    except ValueError as e:
        return {"error": str(e)}, 401
    
    # Track usage
    await auth_middleware.track_usage(user_info["user_id"], tool_name)
    
    # Continue with request...
```

---

### Phase 5: Enable Auth in Production

**File: `.env` (production)**

```bash
REQUIRE_API_KEY=true
FIRESTORE_COLLECTION_USERS=users
```

**Cloud Run deployment:**

```bash
gcloud run services update gammarips-mcp \
  --set-env-vars="REQUIRE_API_KEY=true,FIRESTORE_COLLECTION_USERS=users"
```

---

### Phase 6: Update /developers Page Copy

After auth is enabled, update the developers page:

```tsx
// Remove "Auth: None required during beta"
// Update to:
<p className="text-sm text-muted-foreground">
  Transport: SSE • Auth: API Key (X-API-Key header)
</p>
```

Quick start code:
```tsx
<pre>
{`# Add your API key
curl -H "X-API-Key: gr_live_your_key_here" \
  "https://gammarips-mcp-469352939749.us-central1.run.app/sse"`}
</pre>
```

---

## Service Account Requirements

The MCP server needs Firestore access. It already has this via the GCP project's default service account on Cloud Run.

**If deploying elsewhere**,
you need:
1. Create service account with `roles/datastore.user`
2. Download JSON key
3. Set `GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json`

---

## Firestore Security Rules

Update Firestore rules to protect API key hash:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /users/{userId} {
      // Users can read their own data
      allow read: if request.auth != null && request.auth.uid == userId;
      
      // Users can update their own data (except apiKeyHash which is server-only)
      allow update: if request.auth != null && request.auth.uid == userId
        && !request.resource.data.diff(resource.data).affectedKeys().hasAny(['apiKeyHash']);
      
      // Server (admin SDK) can do anything
    }
  }
}
```

---

## Testing Checklist

1. [ ] Generate API key on /account page
2. [ ] Copy key and verify it starts with `gr_live_`
3. [ ] Test MCP call without key → should get 401
4. [ ] Test MCP call with valid key → should work
5. [ ] Test with expired subscription → should get 401 with helpful message
6. [ ] Regenerate key → old key should stop working
7. [ ] Verify key hash stored in Firestore (never plain key)

---

## Rollback Plan

If issues arise, disable auth:

```bash
gcloud run services update gammarips-mcp \
  --set-env-vars="REQUIRE_API_KEY=false"
```

---

## Commit Messages

```bash
# MCP repo
git commit -m "feat: enable API key authentication for paid users"

# Webapp repo  
git commit -m "feat: add API key generation UI on /account page"
```

