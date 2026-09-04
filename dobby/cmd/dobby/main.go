// Command dobby serves Baymax's authoritative medical reference tools over the
// Model Context Protocol.
package main

import (
	"os"

	"github.com/ArshiAbolghasemi/Baymax/dobby/internal/dobby"
)

func main() {
	os.Exit(dobby.Run())
}
