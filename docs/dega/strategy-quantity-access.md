# Strategy purchase quantities

After deploying the quantity-aware backend and enabling its generated policy:

| Element consumed | Strategy selections | Duration |
|---|---:|---|
| 1 Silver | 1 | 1825 days |
| 1 Golden | 2 | 1825 days |
| 1 Obsidian | 5 | 1825 days |
| 1 Diamond | All, including future strategies | 1825 days |

The first activation spends the Element and selects the highlighted strategy.
Remaining slots can be used later, but all selections share the first activation's
expiry. Selections are fixed. The backend uses existing slots before consuming
another Element, then chooses the cheapest affordable Element type.

Select another strategy to see remaining slots. **Use purchased slot** confirms a
selection with no Element charge. If the slot expires or is used by another session
before confirmation, refresh access and review the new terms; no automatic purchase
is made for that failed slot request.

Installation remains a separate action (`i`). Starts/relaunches check the cached
per-strategy grant first, and recheck remotely after expiry. Existing running
automations continue. Existing purchases retain their original expiration and scope.

Rollout requires backend migration 028, the matching Canon update, and the generated
five-year policy. Merging the client alone does not change production pricing.
