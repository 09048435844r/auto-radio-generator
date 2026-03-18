# Rebase helper script to reword commit messages

$env:GIT_EDITOR = "powershell -NoProfile -Command `"
    `$content = Get-Content `$args[0]
    `$content = `$content -replace 'pick 88c2eca', 'reword 88c2eca'
    `$content = `$content -replace 'pick ec49e85', 'reword ec49e85'
    Set-Content `$args[0] `$content
`""

git rebase -i 88c2eca~1
