$ErrorActionPreference = 'Stop'

$scratch = $PSScriptRoot   # CSV sources live beside this script
$outDir  = Split-Path $PSScriptRoot -Parent   # AI-Task/tests
$outFile = Join-Path $outDir 'Week3-Test-Cases.xlsx'

# sheet name, csv file, widths per column (0 = auto), which columns wrap
$sheets = @(
  @{ Name = 'Setup';            File = 'tc_setup.csv'; Widths = @(6, 46, 40, 40, 12, 48); Wrap = @(2,3,4,6) },
  @{ Name = 'Test Cases';       File = 'tc_main.csv';  Widths = @(9, 18, 18, 22, 46, 44, 60, 34, 30, 11, 52); Wrap = @(4,5,6,7,8,9,11) },
  @{ Name = 'Chunk Experiment'; File = 'tc_chunk.csv'; Widths = @(52, 22, 22, 62); Wrap = @(1,4) },
  @{ Name = 'Risks and Notes';  File = 'tc_risks.csv'; Widths = @(8, 16, 56, 60, 60, 14); Wrap = @(3,4,5) }
)

function Read-PipeTable([string]$path) {
  # Manual split on '|'. No field in the data contains a pipe, so this is exact and
  # immune to the quote-qualifier handling that mangles Import-Csv here.
  $lines = [System.IO.File]::ReadAllLines($path) | Where-Object { $_.Trim().Length -gt 0 }
  $header = $lines[0].Split('|')
  $rows = @()
  for ($i = 1; $i -lt $lines.Count; $i++) {
    $fields = $lines[$i].Split('|')
    if ($fields.Count -ne $header.Count) {
      throw "Row $($i + 1) of $(Split-Path $path -Leaf) has $($fields.Count) fields, expected $($header.Count)"
    }
    $rows += ,$fields
  }
  return @{ Header = $header; Rows = $rows }
}

if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false

try {
  $wb = $excel.Workbooks.Add()

  # Excel starts with a few blank sheets; make sure we have exactly as many as we need.
  while ($wb.Worksheets.Count -lt $sheets.Count) { $wb.Worksheets.Add() | Out-Null }
  while ($wb.Worksheets.Count -gt $sheets.Count) { $wb.Worksheets.Item($wb.Worksheets.Count).Delete() }

  for ($s = 0; $s -lt $sheets.Count; $s++) {
    $spec = $sheets[$s]
    $table = Read-PipeTable (Join-Path $scratch $spec.File)
    $header = $table.Header
    $rows = $table.Rows
    $colCount = $header.Count
    $rowCount = $rows.Count + 1

    $ws = $wb.Worksheets.Item($s + 1)
    $ws.Name = $spec.Name

    # One bulk assignment is far faster and more reliable than cell-by-cell COM calls.
    $data = New-Object 'object[,]' $rowCount, $colCount
    for ($c = 0; $c -lt $colCount; $c++) { $data[0, $c] = $header[$c] }
    for ($r = 0; $r -lt $rows.Count; $r++) {
      # Parentheses are required: PowerShell binds the comma tighter and would
      # otherwise evaluate this as $r + (1, $c), adding an array to an integer.
      for ($c = 0; $c -lt $colCount; $c++) { $data[($r + 1), $c] = $rows[$r][$c] }
    }
    $range = $ws.Range($ws.Cells(1, 1), $ws.Cells($rowCount, $colCount))
    $range.Value2 = $data

    # Header styling
    $head = $ws.Range($ws.Cells(1, 1), $ws.Cells(1, $colCount))
    $head.Font.Bold = $true
    $head.Font.Size = 11
    $head.Font.Color = 16777215                 # white
    $head.Interior.Color = 6303018              # dark teal-slate
    $head.HorizontalAlignment = -4131           # left
    $head.VerticalAlignment = -4108             # centre
    $ws.Rows.Item(1).RowHeight = 30

    # Body
    $body = $ws.Range($ws.Cells(2, 1), $ws.Cells($rowCount, $colCount))
    $body.VerticalAlignment = -4160             # top
    $body.Font.Size = 10

    # Widths and wrapping
    for ($c = 1; $c -le $colCount; $c++) {
      $w = $spec.Widths[$c - 1]
      if ($w -gt 0) { $ws.Columns.Item($c).ColumnWidth = $w }
      if ($spec.Wrap -contains $c) { $ws.Columns.Item($c).WrapText = $true }
    }

    # Borders, freeze the header, and a filter for the long sheets
    $range.Borders.LineStyle = 1
    $range.Borders.Color = 12632256
    $ws.Activate()
    $ws.Range('A2').Select()
    $excel.ActiveWindow.FreezePanes = $true
    if ($colCount -ge 6) { $range.AutoFilter() | Out-Null }
    $ws.Rows.Item("2:$rowCount").AutoFit() | Out-Null

    Write-Output "  sheet '$($spec.Name)': $($rows.Count) rows x $colCount cols"
  }

  $wb.Worksheets.Item('Test Cases').Activate()
  if (Test-Path $outFile) { Remove-Item $outFile -Force }
  $wb.SaveAs($outFile, 51)                      # 51 = xlOpenXMLWorkbook (.xlsx)
  $wb.Close($false)
  Write-Output "SAVED: $outFile"
}
finally {
  $excel.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
