# Coach Selection Bug - Investigation & Fix

## Issue Report

**User symptom:** "I played as Judit Polgar in the selection box but the prompt was for Anna Cramling. I think maybe some of the coaches work and others don't."

## Root Cause Analysis

### Bug Found

**Location:** `src/frontend/main.ts` line 866

**Problem:** On initial page load, `gc.newGame()` was called BEFORE `gc.setCoachName(savedCoach)`, causing the game session to be created with the hardcoded default coach name ("Anna Cramling") instead of the user's selected coach from localStorage.

**Data Flow:**
1. Line 490: `savedCoach` loaded from localStorage → e.g., "Judit Polgar"
2. Line 511: Dropdown displays correct selection → Shows "Judit Polgar"
3. Line 853: `GameController` created with hardcoded `coachName = "Anna Cramling"` (game.ts:75)
4. Line 866: `gc.newGame()` called → Sends "Anna Cramling" to server ❌
5. User makes first move → Gets coaching from "Anna Cramling" instead of "Judit Polgar"

**Why it seemed intermittent:**
- After changing the coach selection manually, it works correctly (line 912-916 calls `setCoachName` before `resetUI()` → `newGame()`)
- Only fails on initial page load

## Fix Applied

### 1. Frontend Initialization Fix

**File:** `src/frontend/main.ts` (line 868)

**Change:** Added `gc.setCoachName(savedCoach);` before `gc.newGame()`

```typescript
// Initialize coach from localStorage before creating session
gc.setCoachName(savedCoach);

// Create initial server session
gc.newGame();
```

### 2. Diagnostic Logging Added

**File:** `src/frontend/game.ts`
- Added console.log when coach is set

**File:** `src/frontend/api.ts`
- Added console.log when API call is made with coach name

**File:** `src/server/game.py`
- Added logging when game session is created with coach name

**File:** `src/server/llm.py`
- Added debug logging when persona is resolved

## Verification

### Backend Tests

All tests pass:
```bash
uv run pytest tests/test_coach_selection_bug.py -v
```

✓ Persona lookup works correctly
✓ Default fallback works
✓ All frontend coaches exist in backend

### Name Matching

All 14 coach names match between frontend dropdown and backend personas:
- Anna Cramling ✓
- Daniel Naroditsky ✓
- GothamChess ✓
- GM Ben Finegold ✓
- Hikaru ✓
- Judit Polgar ✓
- Magnus Carlsen ✓
- Vishy Anand ✓
- Garry Kasparov ✓
- Mikhail Botvinnik ✓
- Paul Morphy ✓
- Mikhail Tal ✓
- Jose Raul Capablanca ✓
- Faustino Oro ✓

## Testing Instructions

### Manual Test

1. Open the app in browser
2. Open browser console (F12)
3. Select a coach (e.g., "Judit Polgar") from dropdown
4. Refresh the page
5. Look for console logs:
   ```
   [GameController] Setting coach to: "Judit Polgar"
   [API] Creating game with coach: "Judit Polgar", elo: "intermediate"
   ```
6. Make a mistake move
7. Verify the coaching message matches the selected coach's persona

### Server Logs

Check server logs for:
```
INFO: Creating new game session abc12345... with coach='Judit Polgar', elo='intermediate'
```

### Debug Mode

Enable debug mode in the hamburger menu to see the full LLM prompt, which should include the correct persona block.

## Related Issues

No other issues found:
- All coach names match between frontend and backend
- No race conditions detected
- Async flow is correct
- localStorage persistence works correctly
