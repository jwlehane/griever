# Specification: Renovations, Multi-County Architecture & Error Reporting

## 1. Effective Age Calculation
- **Requirement:** Support user-provided renovation data to override the chronological "Year Built".
- **Formula:** `Effective Year Built = (Original Year Built + Renovation Year) / 2`.
- **UI:** A follow-up prompt on the report page if comps are poor, or a general "Refine" button.

## 2. County Interface (Abstraction)
- **Goal:** Isolate county-specific API logic to allow future expansion to Ulster County.
- **Methods to Abstract:**
    - `get_property_details(address)`
    - `verify_comp(address)`
    - `get_assessment_data(address)`
- **Factory Logic:** Map zip codes or address patterns to the appropriate county handler.

## 3. Error Reporting
- **Recipient:** `jwlehane@gmail.com`
- **Payload:** Full traceback, request params (address), and the raw response from the external API (if available).
- **User Message:** "The County system is currently experiencing high load or is unavailable. We have reported this issue to our developers. Please try again later."
