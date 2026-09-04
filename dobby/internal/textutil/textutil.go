// Package textutil turns raw upstream content into clean, bounded plain text.
//
// The sources return a mixture of HTML fragments, XML markup and irregular
// whitespace. Everything a tool puts in front of a model goes through Clean
// first, so markup never reaches the model and no single field can exceed its
// configured budget.
package textutil

import (
	"html"
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/beevik/etree"
)

var (
	tagPattern        = regexp.MustCompile(`<[^>]+>`)
	whitespacePattern = regexp.MustCompile(`\s+`)
	// Tags become spaces, so "repairs <b>DNA</b>." collapses to "repairs DNA ."
	// with a space stranded before the punctuation. Closing brackets are
	// included for the same reason; opening ones are not, because "( a" is not
	// a pattern markup removal produces.
	danglingSpacePattern = regexp.MustCompile(`\s+([,.;:!?)\]}])`)
)

// ellipsis marks text cut short by a limit, so a model can tell a truncated
// passage from one that simply ended.
const ellipsis = "…"

// Clean unescapes HTML entities, strips markup, collapses whitespace, and
// truncates to at most limit runes. A limit of zero or less returns "".
func Clean(value string, limit int) string {
	if value == "" || limit <= 0 {
		return ""
	}

	unescaped := html.UnescapeString(value)
	withoutTags := tagPattern.ReplaceAllString(unescaped, " ")
	collapsed := whitespacePattern.ReplaceAllString(withoutTags, " ")
	compact := strings.TrimSpace(danglingSpacePattern.ReplaceAllString(collapsed, "$1"))

	if utf8.RuneCountInString(compact) <= limit {
		return compact
	}
	// Cut on a rune boundary, leaving room for the ellipsis.
	runes := []rune(compact)

	return strings.TrimRight(string(runes[:limit-1]), " ") + ellipsis
}

// FromElement collects the text of an element and all its descendants, then
// cleans it. A nil element yields "".
func FromElement(element *etree.Element, limit int) string {
	if element == nil {
		return ""
	}

	var builder strings.Builder
	collect(element, &builder)

	return Clean(builder.String(), limit)
}

// collect walks the element depth-first, appending every character-data node it
// finds. Separating nodes with a space keeps words from running together when
// markup was the only thing between them.
func collect(element *etree.Element, builder *strings.Builder) {
	for _, token := range element.Child {
		switch node := token.(type) {
		case *etree.CharData:
			builder.WriteString(node.Data)
			builder.WriteString(" ")
		case *etree.Element:
			collect(node, builder)
		}
	}
}
