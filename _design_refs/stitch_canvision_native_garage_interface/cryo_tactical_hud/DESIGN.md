# Design System Strategy: Tactical Command Interface

## 1. Overview & Creative North Star
This design system is built upon the Creative North Star of **"The Tactical Command Interface."** It moves beyond traditional automotive software into the realm of high-performance military instrumentation. The aesthetic mimics a localized Heads-Up Display (HUD) integrated into a physical, dark-ops garage environment. 

To achieve a signature, high-end editorial feel, the system rejects standard symmetrical grids in favor of **Intentional Data Asymmetry**. Layouts should feel like a coordinated tactical brief: vital telemetry is layered over atmospheric depth, using overlapping frosted glass containers and high-contrast technical typography. We are not just building a dashboard; we are building a mission-critical console where every cyan glow represents a live pulse from the vehicle's neural network.

---

## 2. Colors & Atmospheric Depth
The color palette is anchored in deep obsidian tones with high-energy luminescence.

*   **Primary Kinetic Accent:** `primary_container` (`#00ffff`) is our "live" state. It should be used sparingly for critical borders, active status indicators, and focused interactions to maintain its visual impact.
*   **Neutral Foundation:** The background is set to `surface` (`#0b0f0f`), a deep, ink-like black that allows neon accents to pop without washing out the display.

### The "No-Line" Rule
Standard 1px solid dividers are strictly prohibited for structural sectioning. Boundaries between content areas must be defined through:
1.  **Tonal Shifts:** Placing a `surface_container_low` element against a `surface` background.
2.  **Negative Space:** Utilizing the spacing scale to create distinct visual groups.
3.  **The Ghost Border:** For this system, borders are reserved exclusively for "active" containers using the `outline_variant` at 20% opacity or a primary-glow border for high-priority cards.

### Signature Textures: Glassmorphism
To create a sense of "layered data," all major containers utilize a frosted glass effect. This is achieved by combining `surface_container` tokens with a `backdrop-filter: blur(16px)` and a low-opacity alpha channel (e.g., 60%). This allows the "futuristic garage" background environment to bleed through, providing a sense of physical space and atmospheric soul.

---

## 3. Typography: Technical Precision
The typography system uses a dual-font approach to balance brutalist technicality with high-end readability.

*   **Display & Headlines (Space Grotesk):** This is our "Command" typeface. Its wide stance and geometric terminals evoke aerospace engineering. Use `display-lg` for vehicle identifiers and `headline-md` for primary diagnostic sectors.
*   **Body & Labels (Manrope):** A clean, versatile sans-serif used for high-density data. `label-md` and `label-sm` are critical for telemetry readouts, providing a "military brief" look when set in all-caps with increased letter spacing.

The hierarchy is intentionally extreme. We use large `display` scales alongside tiny, precise `labels` to create a "Technical Editorial" look that feels both premium and functional.

---

## 4. Elevation & Depth
Depth in this system is not achieved through shadows, but through **Luminescent Layering**.

*   **The Layering Principle:** Treat the UI as a stack of transparent glass panes. A `surface_container_highest` pane sits "closer" to the user than a `surface_container_low` pane. 
*   **Ambient Glow:** Traditional drop shadows are replaced by "Glow Shadows." When an element is focused, apply a diffused outer glow using the `primary` token (#00ffff) at 10-15% opacity with a large blur radius (20px+). This simulates light refracting through the frosted glass.
*   **Glass & Depth:** Use the `surface_variant` at 40% opacity for cards. The border should be a thin (1px) `primary` glow or a 20% `outline_variant` to define the edge without closing the element off from the environment.

---

## 5. Components

### Buttons (Tactical Triggers)
*   **Geometry:** Strictly rounded rectangles using the `md` (0.375rem) corner radius. **Circular buttons are prohibited.**
*   **Primary Variant:** `surface_container` background with a 1px `primary` border. Apply a subtle `0 0 8px` glow to the border. Text should be `label-md` in `primary` color.
*   **Interaction:** On hover, the background opacity increases, and the glow intensity doubles.

### Frosted Glass Cards
*   **Style:** `surface_container_high` with 60% opacity and `backdrop-filter: blur(12px)`. 
*   **Borders:** Use thin cyan glowing borders (`primary` at 40% opacity).
*   **Layout:** No dividers. Use `title-sm` for headers and `body-sm` for descriptions, separated by at least 1.5rem of vertical space.

### Diagnostic Inputs
*   **Text Fields:** Background-less. Only a bottom-border using `outline_variant`. When focused, the border transforms into a `primary` cyan glow.
*   **Checkboxes & Radios:** Sharp, technical squares (0.125rem radius). No circles. Active states must use a solid `primary` fill with a `primary` glow.

### Additional Components: HUD Overlays
*   **Data Brackets:** Use L-shaped corner accents (using the `primary` color) to frame important diagnostic data points, reinforcing the "Command Console" aesthetic.
*   **Pulse Indicators:** Small 4x4px squares that slowly pulse with a `primary` glow to indicate live data streams.

---

## 6. Do's and Don'ts

### Do:
*   **Do** use asymmetrical layouts where data "hangs" from the edges of the screen, mimicking a HUD.
*   **Do** lean into the "Military Brief" look by using all-caps for labels and small metadata.
*   **Do** use `primary` cyan strictly for interactive or status-critical elements.
*   **Do** ensure all glass containers have a backdrop blur to maintain text legibility over complex backgrounds.

### Don't:
*   **Don't** use circular buttons or heavily rounded "pill" shapes; it breaks the technical, military aesthetic.
*   **Don't** use 100% opaque backgrounds for cards; this destroys the "atmospheric garage" depth.
*   **Don't** use standard grey shadows. If an element needs lift, use light-refraction (glow) or tonal shifting.
*   **Don't** use dividers to separate list items; use white space and `surface-container` shifts.