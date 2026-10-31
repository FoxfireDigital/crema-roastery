// Crema build helper; distributed under the repository's MIT license.
package main

import (
	"crypto/sha256"
	"debug/buildinfo"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

type module struct { Path, Version, Sum, Dir string }
type notice struct { Path string `json:"path"`; SHA256 string `json:"sha256"` }
type component struct { Name string `json:"name"`; Version string `json:"version"`; Sum string `json:"sum,omitempty"`; Notices []notice `json:"notices"` }

func must(err error) { if err != nil { panic(err) } }
func copyNotice(source, destination, root string) notice {
	raw, err := os.ReadFile(source); must(err)
	must(os.MkdirAll(filepath.Dir(destination), 0755)); must(os.WriteFile(destination, raw, 0644))
	sha := sha256.Sum256(raw); relative, err := filepath.Rel(root, destination); must(err)
	return notice{filepath.ToSlash(relative), hex.EncodeToString(sha[:])}
}

func main() {
	if len(os.Args) != 3 { panic("expected binary and metadata output directory") }
	binary, root := os.Args[1], os.Args[2]
	info, err := buildinfo.ReadFile(binary); must(err)
	output, err := exec.Command("go", "list", "-m", "-json", "all").Output(); must(err)
	modules := map[string]module{}
	decoder := json.NewDecoder(strings.NewReader(string(output)))
	for { var item module; err := decoder.Decode(&item); if err == io.EOF { break }; must(err); modules[item.Path] = item }
	standard := component{Name:"Go standard library", Version:info.GoVersion}
	standard.Notices = []notice{copyNotice(filepath.Join(runtime.GOROOT(), "LICENSE"), filepath.Join(root,"notices","go","LICENSE"),root)}
	components := []component{standard}
	for _, dependency := range info.Deps {
		if dependency.Replace != nil { panic("unexpected module replacement") }
		item, ok := modules[dependency.Path]; if !ok || item.Dir == "" { panic("missing exact module source: " + dependency.Path) }
		entry := component{Name:dependency.Path,Version:dependency.Version,Sum:dependency.Sum,Notices:[]notice{}}
		id := sha256.Sum256([]byte(dependency.Path+"@"+dependency.Version)); directory := hex.EncodeToString(id[:8])
		must(filepath.WalkDir(item.Dir, func(path string, file fs.DirEntry, err error) error {
			if err != nil { return err }; if !file.Type().IsRegular() { return nil }
			name := strings.ToLower(file.Name()); wanted := false
			for _, prefix := range []string{"license","copying","copyright","notice"} { if strings.HasPrefix(name,prefix) { wanted=true } }
			if wanted { relative, err := filepath.Rel(item.Dir,path); if err != nil { return err }; entry.Notices=append(entry.Notices,copyNotice(path,filepath.Join(root,"notices",directory,relative),root)) }
			return nil
		}))
		if len(entry.Notices)==0 { panic("missing module notice: "+entry.Name) }
		components=append(components,entry)
	}
	raw, err := os.ReadFile(binary); must(err); digest:=sha256.Sum256(raw)
	report:=map[string]any{"format":"crema-go-components-v1","binarySHA256":hex.EncodeToString(digest[:]),"goVersion":info.GoVersion,"components":components,"limitation":"Compiled modules and available notices; not complete license/source compliance or vulnerability clearance."}
	encoded, err:=json.MarshalIndent(report,"","  "); must(err); must(os.WriteFile(filepath.Join(root,"components.json"),append(encoded,'\n'),0644))
	fmt.Printf("Captured %d compiled component notices.\n",len(components))
}
