# Checkpoint 1 — Open a shared workspace as Alice and Bob

**Status** — Implemented, verified, and accepted by the user after hands-on testing.

Alice and Bob should be able to open the same local workspace in separate browser tabs. Each tab should show who is viewing the workspace and who belongs to it. Refreshing either tab and restarting the API should preserve the result.

## Build order

1. **Seed the workspace.** Scaffold FastAPI in `backend/` with a local SQLite file. Create users, workspaces, and memberships. Give Alice, Bob, and the Launch workspace stable IDs. Use a unique workspace/user pair for each membership and seed all records in one transaction so startup is safe to repeat.
2. **Expose the workspace view.** Add `GET /api/workspaces/launch`. The client sends the selected demo user ID in `X-Demo-User`. The server resolves that user, checks membership, and returns the workspace ID and name, the viewing user, and the member list. The header is a local demo identity selector. Verify that a missing or unknown identity cannot read the workspace.
3. **Build the two-tab flow.** Scaffold React, TypeScript, and Vite in `frontend/`. The entry screen offers **Open as Alice** and **Open as Bob**. Both links target the Launch workspace, with the identity in the URL query string. Each tab derives its identity from its own URL and renders the API response with the workspace name, a “Viewing as” label, and the members. If the request fails, show a readable error.
4. **Prepare the demo files.** Create the three small, text-bearing fixtures below. Open each file and verify the content at its stated location. Upload and extraction are scheduled for checkpoint 2.
5. **Verify and hand off.** Add the exact local startup commands and Alice/Bob links to the README. Run the acceptance test below and record the result before handing the build over for review.

## Fixture contents

| File | Location | Expected content |
| --- | --- | --- |
| `fixtures/launch-brief.pdf` | Page 1 | A short launch brief identifying the campaign and its objective |
| `fixtures/launch-deck.pptx` | Slide 2 | “The launch budget is $120,000.” |
| `fixtures/launch-budget.xlsx` | Budget sheet, rows 2–4 | Row 2 lists media at $80,000, row 3 lists events at $40,000, and row 4 lists the launch budget total of $120,000. |

## Hands-on acceptance test

1. Start the API and frontend using the README commands. Open the entry screen in two tabs of the same browser.
2. Choose Alice in the first tab and Bob in the second. Both tabs should show **Launch** and list **Alice** and **Bob** exactly once. The first tab should say **Viewing as Alice** and the second **Viewing as Bob**.
3. Refresh Bob’s tab, then Alice’s. Each should still show the identity selected for that tab.
4. Restart the API using the same SQLite file and reload both tabs. The workspace, both identities, and the two-member list should match what you saw before the restart.

The user signed off on this walkthrough and requested a checkpoint 2 plan for review.

## Verification results

- Opened the entry screen in two browser tabs, selected Alice and Bob, and refreshed both. Each showed its own viewer and the same two members under Launch.
- Stopped the API, observed the readable load error, restarted it against the same SQLite file, and refreshed both tabs. Both identities and the two-member list were correct.
- Tested the endpoint against a separate database. Alice and Bob received the workspace, missing and unknown identities returned HTTP 401, and a known user without membership received HTTP 403.
- Built the frontend and checked the source files with PDF, PowerPoint, and Excel readers. The campaign brief, slide statement, and spreadsheet amounts were present at the specified locations.
