# Bitly-inspired web interface

Add a responsive, accessible web interface to the existing URL-shortener service. The experience should be
visually inspired by the clarity of Bitly and TinyURL without copying protected branding or assets.

Users must be able to shorten a URL, choose an optional alias and expiration, copy or open the result, and see
clear validation and failure feedback. An administrative workspace should allow an operator to enter the local
admin key, list links, inspect click analytics, and disable links. Preserve the existing JSON API and redirect
behavior, add no frontend build dependency, and keep secrets out of persistent browser storage.
