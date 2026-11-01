// Command shop is a made-up service for the demo.
package main

import (
	"fmt"
	"os"
)

func main() {
	fmt.Println(os.Getenv("DATABASE_URL"), os.Getenv("STRIPE_KEY"), os.Getenv("SENTRY_DSN"), os.Getenv("LOG_LEVEL"))
}
