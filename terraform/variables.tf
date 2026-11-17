variable "poc_callback_url" {
  description = "Exact browser harness callback/logout URL. Use localhost HTTP only for local testing."
  type        = string
  default     = "http://localhost:8040/"

  validation {
    condition     = can(regex("^(http://localhost:[0-9]+/|https://[A-Za-z0-9.-]+(:[0-9]+)?/)$", var.poc_callback_url))
    error_message = "Use a root URL ending in /: http://localhost:PORT/ or https://HOST/. No query or fragment."
  }
}
